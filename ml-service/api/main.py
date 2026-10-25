"""
FastAPI Waste Prediction & Inventory Optimization Engine.

Provides:
- POST /predict/demand: On-demand future demand forecasting (Prophet / PyTorch LSTM)
- POST /risk/score: Real-time 0-100 waste risk scoring & action recommendations
- GET /risk/batch/{business_id}: Multi-tenant batch risk assessment of active inventory
- POST /reorder/recommend: Smart replenishment quantities with transparent reasoning
- GET /health: Service health check
- GET /models/metrics: Benchmark evaluation metrics comparing models vs naive baseline
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Header, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader

from api.config import settings
from api.schemas import (
    BatchRiskResponse,
    DailyForecastItem,
    DemandPredictRequest,
    DemandPredictResponse,
    HealthResponse,
    ReorderRecommendRequest,
    ReorderRecommendResponse,
    RiskScoreRequest,
    RiskScoreResponse,
)
from api.scheduler import (
    run_batch_waste_risk_assessment,
    shutdown_scheduler,
    start_scheduler,
)
from data.generate_data import CATEGORY_PROFILES
from models.baseline_prophet import ProphetForecaster
from models.lstm_model import LSTMForecaster
from reorder.optimizer import recommend_reorder
from risk.risk_scorer import calculate_waste_risk


# Security: API Key validation
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Valid business_id pattern: alphanumeric, underscores, hyphens, 1-64 chars
_BUSINESS_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> str:
    """Validates the X-API-Key request header."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing 'X-API-Key' header in request.",
        )
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key provided.",
        )
    return api_key


def verify_tenant_access(business_id: str) -> str:
    """
    Guards the batch endpoint: validates business_id format and checks it against
    the list of IDs the current API key is permitted to access.

    If ALLOWED_BUSINESS_IDS is empty (dev/single-tenant mode) any well-formed ID
    is accepted — log a warning so operators notice.
    """
    if not _BUSINESS_ID_RE.match(business_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid business_id '{business_id}'. "
                "Only alphanumeric characters, hyphens, and underscores are allowed (max 64 chars)."
            ),
        )

    allowed = settings.ALLOWED_BUSINESS_IDS
    if not allowed:
        # Dev / single-tenant mode — accept any valid ID but warn
        print(
            f"WARNING: ALLOWED_BUSINESS_IDS is not set. "
            f"Accepting business_id='{business_id}' without tenant restriction."
        )
        return business_id

    if business_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access denied: this API key is not authorised to access "
                f"business_id='{business_id}'."
            ),
        )
    return business_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager to start/stop background scheduler."""
    start_scheduler()
    # Perform initial batch evaluation on startup if data exists
    try:
        run_batch_waste_risk_assessment(business_id=settings.DEFAULT_BUSINESS_ID)
    except Exception as e:
        print(f"Warning: Initial batch evaluation skipped: {e}")
    yield
    shutdown_scheduler()


app = FastAPI(
    title="AI-Powered Food Waste Prediction & Optimization API",
    description="Microservice providing demand forecasting, waste-risk scoring, and smart reordering for food inventory.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helper: Load best model choice from metrics.json
def _get_best_model_choice(category: str) -> str:
    cat = category.lower()
    if settings.METRICS_FILE.exists():
        try:
            with open(settings.METRICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(cat, {}).get("best_model", "prophet")
        except Exception:
            pass
    return "prophet"


# -----------------------------------------------------------------------------
# 1. Health Endpoint (Public)
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """System liveness check and model inventory inspection."""
    loaded_models = []
    if settings.MODELS_DIR.exists():
        loaded_models = [p.name for p in settings.MODELS_DIR.glob("*.*")]

    return HealthResponse(
        status="healthy",
        environment=settings.ENVIRONMENT,
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
        models_loaded=loaded_models,
    )


# -----------------------------------------------------------------------------
# 2. Demand Prediction Endpoint
# -----------------------------------------------------------------------------
@app.post(
    "/predict/demand",
    response_model=DemandPredictResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Forecasting"],
)
async def predict_demand(req: DemandPredictRequest):
    """
    Forecasts daily product demand over the specified horizon.
    Selects Prophet or PyTorch LSTM based on model_type or benchmark performance.
    """
    cat = req.category.lower()
    if cat not in CATEGORY_PROFILES:
        valid_cats = list(CATEGORY_PROFILES.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown category '{cat}'. Supported categories: {valid_cats}",
        )

    model_choice = req.model_type
    if model_choice == "best":
        model_choice = _get_best_model_choice(cat)

    unit = CATEGORY_PROFILES[cat]["unit"]
    horizon = req.horizon_days

    today = date.today()
    forecast_items: List[DailyForecastItem] = []

    # Try Prophet model
    if model_choice == "prophet":
        model_file = settings.MODELS_DIR / f"prophet_{cat}.joblib"
        if not model_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prophet model for '{cat}' not found at {model_file}. Please run training first.",
            )
        forecaster = ProphetForecaster.load(model_file)
        forecast_df = forecaster.predict(horizon=horizon)

        for _, row in forecast_df.iterrows():
            forecast_items.append(
                DailyForecastItem(
                    date=pd.to_datetime(row["ds"]).strftime("%Y-%m-%d"),
                    predicted_demand=round(float(row["yhat"]), 2),
                    lower_bound=round(float(row.get("yhat_lower", 0.0)), 2),
                    upper_bound=round(float(row.get("yhat_upper", 0.0)), 2),
                )
            )

    # Try PyTorch LSTM model
    elif model_choice == "lstm":
        model_file = settings.MODELS_DIR / f"lstm_{cat}.pt"
        if not model_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PyTorch LSTM model for '{cat}' not found at {model_file}. Please run training first.",
            )
        forecaster = LSTMForecaster.load(model_file)

        # Ingest recent historical data for lookback window
        tx_file = settings.DATA_DIR / "daily_transactions.csv"
        if not tx_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction history file not found. Please generate data first.",
            )
        tx_df = pd.read_csv(tx_file)
        cat_df = tx_df[tx_df["category"].str.lower() == cat].sort_values("date")
        recent_values = cat_df["sales_qty"].values[-forecaster.lookback :]

        preds = forecaster.predict(recent_history=recent_values, horizon=horizon)

        for i, pred_val in enumerate(preds):
            target_date = today + timedelta(days=i + 1)
            forecast_items.append(
                DailyForecastItem(
                    date=target_date.strftime("%Y-%m-%d"),
                    predicted_demand=round(float(pred_val), 2),
                    lower_bound=max(0.0, round(float(pred_val) * 0.85, 2)),
                    upper_bound=round(float(pred_val) * 1.15, 2),
                )
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported model_type '{model_choice}'",
        )

    total_demand = round(sum(item.predicted_demand for item in forecast_items), 2)

    return DemandPredictResponse(
        category=cat,
        model_used=model_choice,
        unit=unit,
        horizon_days=horizon,
        forecast=forecast_items,
        total_projected_demand=total_demand,
    )


# -----------------------------------------------------------------------------
# 3. Real-Time Waste Risk Scoring Endpoint
# -----------------------------------------------------------------------------
@app.post(
    "/risk/score",
    response_model=RiskScoreResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Risk Scoring"],
)
async def score_waste_risk(req: RiskScoreRequest):
    """
    Computes real-time waste risk score (0-100) and actionable operational diagnosis.
    Handles edge cases: expired items, zero stock, zero demand.
    """
    res = calculate_waste_risk(
        days_to_expiry=req.days_to_expiry,
        current_stock=req.current_stock,
        forecast_demand=req.forecast_demand,
        category=req.category,
    )

    return RiskScoreResponse(
        item_name=req.item_name,
        category=req.category,
        risk_score=res.risk_score,
        risk_level=res.risk_level,
        surplus_qty=res.surplus_qty,
        surplus_ratio=res.surplus_ratio,
        urgency_factor=res.urgency_factor,
        action_recommendation=res.action_recommendation,
    )


# -----------------------------------------------------------------------------
# 4. Multi-Tenant Batch Risk Assessment Endpoint
# -----------------------------------------------------------------------------
@app.get(
    "/risk/batch/{business_id}",
    response_model=BatchRiskResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Risk Scoring"],
)
async def get_batch_risk(
    business_id: str = Depends(verify_tenant_access),
):
    """
    Retrieves or generates the latest batch waste risk assessment for a business tenant.
    """
    batch_file = settings.BATCH_RESULTS_DIR / f"batch_{business_id}_latest.json"
    if batch_file.exists():
        try:
            with open(batch_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return BatchRiskResponse(**data)
        except Exception:
            pass

    # If cached report not found, compute on-demand
    data = run_batch_waste_risk_assessment(business_id=business_id, save_output=True)
    return BatchRiskResponse(**data)


# -----------------------------------------------------------------------------
# 5. Smart Reorder Recommendation Endpoint
# -----------------------------------------------------------------------------
@app.post(
    "/reorder/recommend",
    response_model=ReorderRecommendResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Replenishment"],
)
async def recommend_reorder_endpoint(req: ReorderRecommendRequest):
    """
    Calculates optimal replenishment quantity with transparent reasoning.
    If forecast_lead_demand is omitted, the endpoint queries the trained Prophet
    or LSTM model (selected by metrics.json best_model) to estimate cumulative
    demand over the supplier lead time.  Falls back to the category profile
    base_demand heuristic only when the model file is missing.
    """
    cat = req.category.lower()

    # If lead demand not provided, derive it from the trained forecasting model
    lead_demand = req.forecast_lead_demand
    if lead_demand is None:
        horizon = req.lead_time_days
        model_choice = _get_best_model_choice(cat)
        forecast_sum: Optional[float] = None

        if model_choice == "prophet":
            model_file = settings.MODELS_DIR / f"prophet_{cat}.joblib"
            if model_file.exists():
                try:
                    forecaster = ProphetForecaster.load(model_file)
                    forecast_df = forecaster.predict(horizon=horizon)
                    forecast_sum = float(forecast_df["yhat"].clip(lower=0.0).sum())
                except Exception as exc:
                    print(f"[reorder] Prophet inference failed for '{cat}': {exc}. Using heuristic.")
        else:
            model_file = settings.MODELS_DIR / f"lstm_{cat}.pt"
            tx_file = settings.DATA_DIR / "daily_transactions.csv"
            if model_file.exists() and tx_file.exists():
                try:
                    forecaster_lstm = LSTMForecaster.load(model_file)
                    tx_df = pd.read_csv(tx_file)
                    cat_df = tx_df[tx_df["category"].str.lower() == cat].sort_values("date")
                    recent = cat_df["sales_qty"].values[-forecaster_lstm.lookback:]
                    if len(recent) >= forecaster_lstm.lookback:
                        preds = forecaster_lstm.predict(recent_history=recent, horizon=horizon)
                        forecast_sum = float(np.clip(preds, 0.0, None).sum())
                except Exception as exc:
                    print(f"[reorder] LSTM inference failed for '{cat}': {exc}. Using heuristic.")

        if forecast_sum is not None:
            lead_demand = forecast_sum
        else:
            # Heuristic fallback: category base_demand scaled by lead time
            profile = CATEGORY_PROFILES.get(cat, {"base_demand": 45.0})
            lead_demand = profile["base_demand"] * req.lead_time_days

    rec = recommend_reorder(
        category=cat,
        current_stock=req.current_stock,
        forecast_lead_demand=lead_demand,
        lead_time_days=req.lead_time_days,
        storage_capacity=req.storage_capacity,
        safety_stock=req.safety_stock,
        shelf_life_days=req.shelf_life_days,
        min_order_qty=req.min_order_qty,
    )

    return ReorderRecommendResponse(
        category=cat,
        recommended_order_qty=rec.recommended_order_qty,
        status=rec.status,
        target_stock=rec.target_stock,
        safety_stock=rec.safety_stock,
        current_stock=rec.current_stock,
        storage_capacity=rec.storage_capacity,
        capacity_utilized_pct=rec.capacity_utilized_pct,
        reasoning=rec.reasoning,
    )


# -----------------------------------------------------------------------------
# 6. Evaluation Metrics Endpoint
# -----------------------------------------------------------------------------
@app.get("/models/metrics", dependencies=[Depends(verify_api_key)], tags=["Forecasting"])
async def get_model_metrics():
    """
    Returns benchmark comparison metrics (MAE, RMSE, MAPE vs Naive baseline)
    for all categories.
    """
    if not settings.METRICS_FILE.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model metrics file not found. Please run training pipeline first.",
        )
    with open(settings.METRICS_FILE, "r", encoding="utf-8") as f:
        metrics = json.load(f)
    return metrics
