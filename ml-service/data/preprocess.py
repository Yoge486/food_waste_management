"""
Data Preprocessing Pipeline for Food Waste Forecasting and Risk Engine.

Includes:
1. Cleaning and type validation
2. Missing-day detection & zero/calendar filling
3. Outlier handling (IQR-based robust clipping)
4. Per-category daily time-series aggregation
5. Chronological (time-based) train/validation/test splitting (zero lookahead leakage)
6. Sliding window sequence generation for LSTM
7. Milestone 1 InventoryItem snapshot validator
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


INDIAN_HOLIDAYS = {
    (1, 26),   # Republic Day
    (5, 1),    # Maharashtra Day / Labour Day
    (8, 15),   # Independence Day
    (10, 2),   # Gandhi Jayanti
}
INDIAN_FESTIVAL_DATES = {
    date(2025, 3, 14),  # Holi
    date(2025, 10, 20),  # Diwali
    date(2026, 3, 4),  # Holi
    date(2026, 11, 8),  # Diwali
}


REQUIRED_TX_COLUMNS = [
    "date",
    "business_id",
    "category",
    "sales_qty",
    "purchase_qty",
    "waste_qty",
]

REQUIRED_INVENTORY_COLUMNS = [
    "name",
    "category",
    "quantity",
    "unit",
    "purchase_date",
    "expiry_date",
]


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans transaction dataframe:
    - Verifies required columns
    - Parses dates
    - Enforces non-negative numerical values
    - Sorts chronologically
    """
    df = df.copy()

    for col in REQUIRED_TX_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Missing required transaction column: {col}")

    # Standardize string fields
    df["business_id"] = df["business_id"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip().str.lower()
    if "unit" in df.columns:
        df["unit"] = df["unit"].astype(str).str.strip()

    # Parse dates
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Numerical coercion and clipping
    for num_col in ["sales_qty", "purchase_qty", "waste_qty"]:
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce").fillna(0.0)
        df[num_col] = df[num_col].clip(lower=0.0)

    # Deduplicate by (date, business_id, category) by summing quantities
    grouped = (
        df.groupby(["date", "business_id", "category"], as_index=False)
        .agg({
            "sales_qty": "sum",
            "purchase_qty": "sum",
            "waste_qty": "sum",
            "unit": "first" if "unit" in df.columns else lambda _: "kg",
        })
        .sort_values(by=["business_id", "category", "date"])
        .reset_index(drop=True)
    )

    return grouped


def fill_missing_days(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensures an uninterrupted daily calendar for each (business_id, category) pair.
    Missing days are filled with 0.0 sales/purchases/waste.
    """
    df = clean_transactions(df)
    filled_dfs = []

    for (biz_id, cat), sub_df in df.groupby(["business_id", "category"]):
        min_date = sub_df["date"].min()
        max_date = sub_df["date"].max()

        full_calendar = pd.date_range(start=min_date, end=max_date, freq="D").date
        calendar_df = pd.DataFrame({"date": full_calendar})
        calendar_df["business_id"] = biz_id
        calendar_df["category"] = cat

        merged = pd.merge(calendar_df, sub_df, on=["date", "business_id", "category"], how="left")
        merged["sales_qty"] = merged["sales_qty"].fillna(0.0)
        merged["purchase_qty"] = merged["purchase_qty"].fillna(0.0)
        merged["waste_qty"] = merged["waste_qty"].fillna(0.0)
        if "unit" in sub_df.columns and not sub_df["unit"].empty:
            merged["unit"] = merged["unit"].ffill().bfill().fillna("kg")

        filled_dfs.append(merged)

    if not filled_dfs:
        return df

    result = pd.concat(filled_dfs, ignore_index=True)
    return result.sort_values(by=["business_id", "category", "date"]).reset_index(drop=True)


def handle_outliers(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
    iqr_multiplier: float = 2.5,
) -> pd.DataFrame:
    """
    Clips extreme outliers per (business_id, category) using robust IQR thresholding.
    Uses 2.5 * IQR by default to allow genuine holiday/weekend demand spikes while capping errors.
    """
    if columns is None:
        columns = ["sales_qty", "waste_qty"]

    df = df.copy()
    for (biz, cat), group_indices in df.groupby(["business_id", "category"]).groups.items():
        for col in columns:
            vals = df.loc[group_indices, col]
            q25 = vals.quantile(0.25)
            q75 = vals.quantile(0.75)
            iqr = q75 - q25
            upper_bound = q75 + (iqr_multiplier * iqr)
            # We don't cap at bottom below zero
            df.loc[group_indices, col] = vals.clip(lower=0.0, upper=upper_bound)

    return df


def prepare_category_series(
    df: pd.DataFrame,
    category: str,
    business_id: Optional[str] = None,
    target_col: str = "sales_qty",
) -> pd.DataFrame:
    """
    Prepares a ready-to-forecast time-series dataframe for a specific category.
    Outputs:
    - 'ds': datetime column for Prophet / PyTorch
    - 'y': target demand/sales value
    - 'day_of_week': 0-6 integer feature
    - 'is_weekend': binary feature
    """
    sub = df[df["category"].str.lower() == category.lower()].copy()
    if business_id:
        sub = sub[sub["business_id"] == business_id]

    if sub.empty:
        raise ValueError(f"No records found for category '{category}' and business '{business_id}'")

    # Aggregate by date if multiple businesses are combined
    daily = (
        sub.groupby("date", as_index=False)
        .agg({target_col: "sum", "waste_qty": "sum", "purchase_qty": "sum"})
        .sort_values("date")
        .reset_index(drop=True)
    )

    daily["ds"] = pd.to_datetime(daily["date"])
    daily["y"] = daily[target_col].astype(float)
    daily["day_of_week"] = daily["ds"].dt.dayofweek
    daily["is_weekend"] = daily["day_of_week"].isin([5, 6]).astype(int)
    daily["is_indian_holiday"] = daily["ds"].map(
        lambda value: int(
            (value.month, value.day) in INDIAN_HOLIDAYS
            or value.date() in INDIAN_FESTIVAL_DATES
        )
    )
    daily["units_sold"] = daily[target_col].astype(float)
    daily["units_wasted"] = daily["waste_qty"].astype(float)

    return daily[
        [
            "ds",
            "y",
            "units_sold",
            "units_wasted",
            "day_of_week",
            "is_weekend",
            "is_indian_holiday",
            "purchase_qty",
            "waste_qty",
        ]
    ]


def time_based_split(
    df: pd.DataFrame,
    val_days: int = 30,
    test_days: int = 30,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Splits time series chronologically to eliminate future lookahead bias:
    - train: earliest days up to T - (val_days + test_days)
    - val: next val_days
    - test: final test_days
    """
    total_days = len(df)
    if total_days < (val_days + test_days + 14):
        raise ValueError(f"Time series length ({total_days}) is too short for split: val={val_days}, test={test_days}")

    train_end = total_days - (val_days + test_days)
    val_end = total_days - test_days

    train_df = df.iloc[:train_end].copy().reset_index(drop=True)
    val_df = df.iloc[train_end:val_end].copy().reset_index(drop=True)
    test_df = df.iloc[val_end:].copy().reset_index(drop=True)

    return train_df, val_df, test_df


def create_sliding_windows(
    values: np.ndarray,
    lookback: int = 14,
    horizon: int = 1,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Transforms 1D time-series into supervised (X, y) sliding windows for LSTM.
    X: shape (num_samples, lookback, 1)
    y: shape (num_samples, horizon)
    """
    X, y = [], []
    for i in range(len(values) - lookback - horizon + 1):
        window = values[i : i + lookback]
        target = values[i + lookback : i + lookback + horizon]
        X.append(window)
        y.append(target)

    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    if X_arr.ndim == 2:
        X_arr = np.expand_dims(X_arr, axis=-1)
    if y_arr.ndim == 1:
        y_arr = np.expand_dims(y_arr, axis=-1)

    return X_arr, y_arr


def clean_inventory_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validates and standardizes active inventory records matching Milestone 1 InventoryItem.
    """
    df = df.copy()
    for col in REQUIRED_INVENTORY_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Missing required inventory column: {col}")

    df["name"] = df["name"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip().str.lower()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0).clip(lower=0.0)
    df["unit"] = df["unit"].astype(str).str.strip().replace("", "kg")
    df["purchase_date"] = pd.to_datetime(df["purchase_date"]).dt.date
    df["expiry_date"] = pd.to_datetime(df["expiry_date"]).dt.date

    if "storage_location" not in df.columns:
        df["storage_location"] = "Main storage"
    else:
        df["storage_location"] = df["storage_location"].fillna("Main storage")

    if "risk_level" not in df.columns:
        df["risk_level"] = "low"

    if "notes" not in df.columns:
        df["notes"] = ""

    return df
