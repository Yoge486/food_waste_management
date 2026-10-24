"""
Unit tests for the batch scheduler's model-driven demand forecasting.

These tests verify:
- _get_forecast_demand returns non-negative float for a valid category
- the heuristic fallback fires when model files are absent
- run_batch_waste_risk_assessment returns the correct schema
- the tenant isolation fix: unknown business_id returns empty items list
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from api.scheduler import _get_forecast_demand, _heuristic_demand, run_batch_waste_risk_assessment


# ---------------------------------------------------------------------------
# _heuristic_demand
# ---------------------------------------------------------------------------

def test_heuristic_demand_positive():
    """Static fallback must return a positive number for any valid category."""
    result = _heuristic_demand("dairy", horizon=7)
    assert result > 0.0


def test_heuristic_demand_scales_with_horizon():
    d3 = _heuristic_demand("produce", horizon=3)
    d6 = _heuristic_demand("produce", horizon=6)
    assert d6 > d3


# ---------------------------------------------------------------------------
# _get_forecast_demand — heuristic path (model file absent)
# ---------------------------------------------------------------------------

def test_get_forecast_demand_falls_back_when_no_model_file(tmp_path):
    """When model files don't exist in MODELS_DIR, expect heuristic fallback (no exception)."""
    from api import config as cfg
    original_dir = cfg.settings.MODELS_DIR
    # Point MODELS_DIR at an empty temp directory so no .joblib/.pt files exist
    cfg.settings.MODELS_DIR = tmp_path

    try:
        result = _get_forecast_demand(
            cat="dairy",
            horizon=5,
            best_model_map={"dairy": "prophet"},
            prophet_cache={},
            lstm_cache={},
            tx_df=None,
        )
        assert isinstance(result, float)
        assert result > 0.0
    finally:
        cfg.settings.MODELS_DIR = original_dir


def test_get_forecast_demand_zero_horizon():
    """horizon=0 (already expired) must return 0.0 without touching any model."""
    result = _get_forecast_demand(
        cat="dairy",
        horizon=0,
        best_model_map={"dairy": "prophet"},
        prophet_cache={},
        lstm_cache={},
        tx_df=None,
    )
    assert result == 0.0


# ---------------------------------------------------------------------------
# _get_forecast_demand — Prophet path (mocked model)
# ---------------------------------------------------------------------------

def test_get_forecast_demand_prophet_uses_cached_model():
    """Once a Prophet model is loaded it should be reused from the cache."""
    mock_forecaster = MagicMock()
    mock_forecaster.predict.return_value = pd.DataFrame({
        "ds": pd.date_range("2026-01-01", periods=7),
        "yhat": [40.0] * 7,
        "yhat_lower": [35.0] * 7,
        "yhat_upper": [45.0] * 7,
    })

    cache: dict = {"dairy": mock_forecaster}
    result = _get_forecast_demand(
        cat="dairy",
        horizon=7,
        best_model_map={"dairy": "prophet"},
        prophet_cache=cache,
        lstm_cache={},
        tx_df=None,
    )

    mock_forecaster.predict.assert_called_once_with(horizon=7)
    assert abs(result - 280.0) < 0.1  # 40 * 7


# ---------------------------------------------------------------------------
# run_batch_waste_risk_assessment
# ---------------------------------------------------------------------------

def _make_inventory_csv(tmp_path: Path, business_id: str = "biz_001") -> Path:
    """Creates a minimal inventory_snapshot.csv fixture in tmp_path."""
    today = date.today()
    rows = [
        {
            "name": f"Whole Milk 1L ({business_id})",
            "category": "dairy",
            "quantity": 30.0,
            "unit": "kg",
            "purchase_date": (today - timedelta(days=3)).isoformat(),
            "expiry_date": (today + timedelta(days=5)).isoformat(),
            "storage_location": "Cold Room A",
            "risk_level": "medium",
            "notes": "",
        },
        {
            "name": f"Sourdough Loaf ({business_id})",
            "category": "bakery",
            "quantity": 10.0,
            "unit": "kg",
            "purchase_date": (today - timedelta(days=1)).isoformat(),
            "expiry_date": (today + timedelta(days=1)).isoformat(),
            "storage_location": "Bakery Rack 1",
            "risk_level": "high",
            "notes": "",
        },
    ]
    inv_file = tmp_path / "inventory_snapshot.csv"
    pd.DataFrame(rows).to_csv(inv_file, index=False)
    return inv_file


def test_batch_assessment_returns_correct_schema(tmp_path):
    inv_file = _make_inventory_csv(tmp_path)
    result = run_batch_waste_risk_assessment(
        business_id="biz_001",
        inventory_file=inv_file,
        save_output=False,
    )
    assert result["business_id"] == "biz_001"
    assert result["total_items"] == 2
    assert isinstance(result["items"], list)
    assert len(result["items"]) == 2
    for item in result["items"]:
        assert 0.0 <= item["risk_score"] <= 100.0
        assert item["risk_level"] in ["Low", "Medium", "High", "Critical"]
        assert item["forecast_demand"] >= 0.0


def test_batch_assessment_unknown_tenant_returns_empty(tmp_path):
    """An unknown business_id should return an empty items list, not another tenant's data."""
    inv_file = _make_inventory_csv(tmp_path, business_id="biz_001")
    result = run_batch_waste_risk_assessment(
        business_id="biz_unknown_9999",
        inventory_file=inv_file,
        save_output=False,
    )
    assert result["total_items"] == 0
    assert result["items"] == []


def test_batch_assessment_missing_inventory_file(tmp_path):
    """Non-existent inventory file must return a safe empty response, not raise."""
    missing = tmp_path / "does_not_exist.csv"
    result = run_batch_waste_risk_assessment(
        business_id="biz_001",
        inventory_file=missing,
        save_output=False,
    )
    assert result["total_items"] == 0
