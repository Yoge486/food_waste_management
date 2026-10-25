"""
Pydantic Request and Response schemas for FastAPI ML Service.
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class DemandPredictRequest(BaseModel):
    category: str = Field(..., description="Category: dairy, bakery, produce, meat, packaged, beverages")
    horizon_days: int = Field(14, ge=1, le=90, description="Forecast horizon in days (default: 14)")
    model_type: Literal["best", "prophet", "lstm"] = Field(
        "best",
        description="Forecasting model to use ('best' selects lowest test error)",
    )
    business_id: Optional[str] = Field(None, description="Optional business tenant ID filter")


class DailyForecastItem(BaseModel):
    date: str
    predicted_demand: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None


class WeeklyForecastItem(BaseModel):
    week_start: str          # ISO date of Monday that starts the week
    week_label: str          # e.g. "Week 1 (Oct 27 – Nov 2)"
    total_demand: float
    avg_daily_demand: float
    days: int                # number of forecast days in this week


class DemandPredictResponse(BaseModel):
    category: str
    model_used: str
    unit: str
    horizon_days: int
    forecast: List[DailyForecastItem]
    weekly_summary: List[WeeklyForecastItem]   # aggregated weekly view
    total_projected_demand: float


class RiskScoreRequest(BaseModel):
    days_to_expiry: int = Field(..., description="Days until expiration (<= 0 indicates expired)")
    current_stock: float = Field(..., ge=0.0, description="Current quantity in stock")
    forecast_demand: float = Field(..., ge=0.0, description="Cumulative projected demand over shelf life")
    category: Optional[str] = Field(None, description="Product category")
    item_name: Optional[str] = Field(None, description="Item name for logging and diagnostic reports")


class RiskScoreResponse(BaseModel):
    item_name: Optional[str] = None
    category: Optional[str] = None
    risk_score: float = Field(..., ge=0.0, le=100.0)
    risk_level: Literal["Low", "Medium", "High", "Critical"]
    surplus_qty: float
    surplus_ratio: float
    urgency_factor: float
    action_recommendation: str


class BatchRiskItem(BaseModel):
    name: str
    category: str
    quantity: float
    unit: str
    days_to_expiry: int
    forecast_demand: float
    risk_score: float
    risk_level: str
    surplus_qty: float
    action_recommendation: str


class BatchRiskResponse(BaseModel):
    business_id: str
    evaluated_at: str
    total_items: int
    high_or_critical_count: int
    average_risk_score: float
    items: List[BatchRiskItem]


class ReorderRecommendRequest(BaseModel):
    category: str = Field(..., description="Product category")
    current_stock: float = Field(..., ge=0.0, description="Current quantity on hand")
    forecast_lead_demand: Optional[float] = Field(
        None,
        ge=0.0,
        description="Projected demand over supplier lead time. If omitted, estimated automatically.",
    )
    lead_time_days: int = Field(2, ge=1, le=30, description="Supplier lead time in days")
    storage_capacity: Optional[float] = Field(None, ge=1.0, description="Storage space ceiling")
    safety_stock: Optional[float] = Field(None, ge=0.0, description="Explicit safety stock buffer")
    shelf_life_days: Optional[int] = Field(None, ge=1, description="Perishable shelf life ceiling in days")
    min_order_qty: float = Field(0.0, ge=0.0, description="Supplier MOQ threshold")


class ReorderRecommendResponse(BaseModel):
    category: str
    recommended_order_qty: float
    status: Literal["ORDER_RECOMMENDED", "SUFFICIENT_STOCK", "CAPACITY_CONSTRAINED", "SHELF_LIFE_CONSTRAINED"]
    target_stock: float
    safety_stock: float
    current_stock: float
    storage_capacity: float
    capacity_utilized_pct: float
    reasoning: str


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
    timestamp: str
    models_loaded: List[str]
