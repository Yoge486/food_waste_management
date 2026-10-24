"""
APScheduler Background Batch Prediction Job.

Runs periodically (daily at 02:00 AM by default) to:
1. Ingest active inventory records from data/inventory_snapshot.csv
2. Query trained forecasting models to estimate cumulative demand over each
   item's remaining shelf-life (Prophet or LSTM, selected by metrics.json)
3. Compute waste risk scores for every active inventory item
4. Persist batch results to reports/batch_predictions/batch_<business_id>_latest.json
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Dict, Optional
import numpy as np
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.config import settings
from data.generate_data import CATEGORY_PROFILES
from models.baseline_prophet import ProphetForecaster
from models.lstm_model import LSTMForecaster
from risk.risk_scorer import calculate_waste_risk

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_best_model_map() -> Dict[str, str]:
    """Returns {category: 'prophet'|'lstm'} from metrics.json, defaulting to prophet."""
    if not settings.METRICS_FILE.exists():
        return {}
    try:
        with open(settings.METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {cat: val.get("best_model", "prophet") for cat, val in data.items()}
    except Exception as exc:
        print(f"[scheduler] Warning: could not load metrics.json: {exc}")
        return {}


def _get_forecast_demand(
    cat: str,
    horizon: int,
    best_model_map: Dict[str, str],
    prophet_cache: Dict[str, ProphetForecaster],
    lstm_cache: Dict[str, LSTMForecaster],
    tx_df: Optional[pd.DataFrame],
) -> float:
    """
    Returns cumulative forecast demand for `cat` over the next `horizon` days
    using the trained Prophet or LSTM model.

    Model instances are cached in `prophet_cache` / `lstm_cache` so each model
    is loaded only once per batch run.

    Falls back to the static category profile heuristic if:
    - The model file does not exist
    - Loading or inference raises an exception
    Fallback cases are logged so operators can spot missing artifacts.
    """
    if horizon <= 0:
        return 0.0

    model_choice = best_model_map.get(cat, "prophet")

    # ---- Prophet ----
    if model_choice == "prophet":
        if cat not in prophet_cache:
            model_file = settings.MODELS_DIR / f"prophet_{cat}.joblib"
            if not model_file.exists():
                print(f"[scheduler] Prophet model for '{cat}' not found at {model_file}. Using heuristic fallback.")
                return _heuristic_demand(cat, horizon)
            try:
                prophet_cache[cat] = ProphetForecaster.load(model_file)
            except Exception as exc:
                print(f"[scheduler] Failed to load Prophet model for '{cat}': {exc}. Using heuristic fallback.")
                return _heuristic_demand(cat, horizon)

        forecaster = prophet_cache[cat]
        try:
            forecast_df = forecaster.predict(horizon=horizon)
            return float(forecast_df["yhat"].clip(lower=0.0).sum())
        except Exception as exc:
            print(f"[scheduler] Prophet inference failed for '{cat}': {exc}. Using heuristic fallback.")
            return _heuristic_demand(cat, horizon)

    # ---- LSTM ----
    if cat not in lstm_cache:
        model_file = settings.MODELS_DIR / f"lstm_{cat}.pt"
        if not model_file.exists():
            print(f"[scheduler] LSTM model for '{cat}' not found at {model_file}. Using heuristic fallback.")
            return _heuristic_demand(cat, horizon)
        try:
            lstm_cache[cat] = LSTMForecaster.load(model_file)
        except Exception as exc:
            print(f"[scheduler] Failed to load LSTM model for '{cat}': {exc}. Using heuristic fallback.")
            return _heuristic_demand(cat, horizon)

    lstm = lstm_cache[cat]

    # LSTM needs recent history for the lookback window.
    # Use the daily_transactions CSV if available; otherwise fall back to heuristic.
    if tx_df is None or tx_df.empty:
        print(f"[scheduler] No transaction history for LSTM '{cat}'. Using heuristic fallback.")
        return _heuristic_demand(cat, horizon)

    cat_series = tx_df[tx_df["category"].str.lower() == cat].sort_values("date")
    recent = cat_series["sales_qty"].values[-lstm.lookback:]

    if len(recent) < lstm.lookback:
        print(
            f"[scheduler] Insufficient history for LSTM '{cat}' "
            f"(have {len(recent)}, need {lstm.lookback}). Using heuristic fallback."
        )
        return _heuristic_demand(cat, horizon)

    try:
        preds = lstm.predict(recent_history=recent, horizon=horizon)
        return float(np.clip(preds, 0.0, None).sum())
    except Exception as exc:
        print(f"[scheduler] LSTM inference failed for '{cat}': {exc}. Using heuristic fallback.")
        return _heuristic_demand(cat, horizon)


def _heuristic_demand(cat: str, horizon: int) -> float:
    """
    Static fallback: category base_demand divided across 3 assumed tenants,
    scaled by the number of remaining days.
    Used only when a trained model file is missing or inference fails.
    """
    profile = CATEGORY_PROFILES.get(cat, {"base_demand": 40.0})
    daily_rate = profile["base_demand"] / 3.0
    return round(daily_rate * max(1, horizon), 2)


# ---------------------------------------------------------------------------
# Main batch function
# ---------------------------------------------------------------------------

def run_batch_waste_risk_assessment(
    business_id: str = "biz_001",
    inventory_file: Path | None = None,
    save_output: bool = True,
) -> Dict:
    """
    Executes a complete batch assessment for a specific business tenant.

    For each active inventory item:
    - Loads the per-category best model (Prophet or LSTM) from metrics.json
    - Predicts cumulative demand over the item's remaining shelf-life
    - Computes waste risk score (0-100) using days-to-expiry + stock + forecast
    """
    if inventory_file is None:
        inventory_file = settings.DATA_DIR / "inventory_snapshot.csv"

    if not inventory_file.exists():
        return {
            "business_id": business_id,
            "evaluated_at": datetime.now().isoformat(),
            "total_items": 0,
            "high_or_critical_count": 0,
            "average_risk_score": 0.0,
            "items": [],
        }

    df = pd.read_csv(inventory_file)

    # Filter items belonging to this business tenant.
    # Synthetic data embeds the business_id in item names, e.g. "Whole Milk 1L (biz_001)".
    # If no items match, return an empty result rather than leaking other tenants' data.
    if "name" in df.columns:
        biz_items = df[df["name"].str.contains(business_id, case=False, na=False)].copy()
    else:
        biz_items = df.copy()

    if biz_items.empty:
        return {
            "business_id": business_id,
            "evaluated_at": datetime.now().isoformat(),
            "total_items": 0,
            "high_or_critical_count": 0,
            "average_risk_score": 0.0,
            "items": [],
        }

    # Load best-model map and transaction history once for the whole batch
    best_model_map = _load_best_model_map()

    tx_df: Optional[pd.DataFrame] = None
    tx_file = settings.DATA_DIR / "daily_transactions.csv"
    if tx_file.exists():
        try:
            tx_df = pd.read_csv(tx_file)
        except Exception as exc:
            print(f"[scheduler] Warning: could not load transaction history: {exc}")

    # Per-category model caches (load each model at most once per batch run)
    prophet_cache: Dict[str, ProphetForecaster] = {}
    lstm_cache: Dict[str, LSTMForecaster] = {}

    evaluated_items = []
    total_score = 0.0
    high_or_crit = 0
    today = date.today()

    for _, row in biz_items.iterrows():
        cat = str(row.get("category", "dairy")).lower()
        item_name = str(row.get("name", "Unknown Item"))
        quantity = float(row.get("quantity", 0.0))
        unit = str(row.get("unit", "kg"))

        # Calculate days to expiry
        try:
            exp_date = pd.to_datetime(row["expiry_date"]).date()
            days_left = (exp_date - today).days
        except Exception:
            days_left = 3

        # Forecast cumulative demand over the remaining shelf-life using trained model
        forecast_demand = _get_forecast_demand(
            cat=cat,
            horizon=max(1, days_left),
            best_model_map=best_model_map,
            prophet_cache=prophet_cache,
            lstm_cache=lstm_cache,
            tx_df=tx_df,
        )

        risk_res = calculate_waste_risk(
            days_to_expiry=days_left,
            current_stock=quantity,
            forecast_demand=forecast_demand,
            category=cat,
        )

        total_score += risk_res.risk_score
        if risk_res.risk_level in ["High", "Critical"]:
            high_or_crit += 1

        evaluated_items.append({
            "name": item_name,
            "category": cat,
            "quantity": quantity,
            "unit": unit,
            "days_to_expiry": days_left,
            "forecast_demand": round(forecast_demand, 2),
            "risk_score": risk_res.risk_score,
            "risk_level": risk_res.risk_level,
            "surplus_qty": risk_res.surplus_qty,
            "action_recommendation": risk_res.action_recommendation,
        })

    # Sort descending by risk score (most critical items first)
    evaluated_items.sort(key=lambda x: x["risk_score"], reverse=True)

    n = len(evaluated_items)
    avg_score = round(total_score / n, 1) if n > 0 else 0.0

    result_payload = {
        "business_id": business_id,
        "evaluated_at": datetime.now().isoformat(),
        "total_items": n,
        "high_or_critical_count": high_or_crit,
        "average_risk_score": avg_score,
        "items": evaluated_items,
    }

    if save_output:
        out_file = settings.BATCH_RESULTS_DIR / f"batch_{business_id}_latest.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2)

    return result_payload


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler():
    """Starts the APScheduler background thread."""
    if not scheduler.running:
        # Schedule daily batch job at 02:00 AM
        scheduler.add_job(
            run_batch_waste_risk_assessment,
            trigger="cron",
            hour=2,
            minute=0,
            id="daily_waste_risk_batch",
            replace_existing=True,
        )
        scheduler.start()


def shutdown_scheduler():
    """Stops the APScheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
