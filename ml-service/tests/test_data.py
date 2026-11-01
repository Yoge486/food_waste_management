"""
Unit tests for Step 1: Data layer (generator and preprocessing pipeline).
"""

from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest

from data.generate_data import (
    CATEGORY_PROFILES,
    generate_inventory_snapshot,
    generate_synthetic_transactions,
)
from data.preprocess import (
    clean_inventory_snapshot,
    clean_transactions,
    create_sliding_windows,
    fill_missing_days,
    handle_outliers,
    prepare_category_series,
    time_based_split,
)


def test_synthetic_transactions_generation():
    days = 60
    businesses = ["biz_test_1", "biz_test_2"]
    df = generate_synthetic_transactions(days=days, businesses=businesses, seed=123)

    assert not df.empty
    expected_rows = days * len(businesses) * len(CATEGORY_PROFILES)
    assert len(df) == expected_rows

    expected_cols = {"date", "business_id", "category", "sales_qty", "purchase_qty", "waste_qty", "unit"}
    assert expected_cols.issubset(set(df.columns))

    # Assert non-negative quantities
    assert (df["sales_qty"] >= 0).all()
    assert (df["purchase_qty"] >= 0).all()
    assert (df["waste_qty"] >= 0).all()


def test_inventory_snapshot_schema_milestone1_compatibility():
    businesses = ["biz_test"]
    inv_df = generate_inventory_snapshot(businesses=businesses, seed=42)

    required_milestone1_cols = [
        "name",
        "category",
        "quantity",
        "unit",
        "purchase_date",
        "expiry_date",
        "storage_location",
        "risk_level",
        "notes",
    ]
    for col in required_milestone1_cols:
        assert col in inv_df.columns, f"Missing Milestone 1 column: {col}"

    assert (inv_df["quantity"] >= 0).all()
    assert set(inv_df["risk_level"].unique()).issubset({"low", "medium", "high", "critical"})


def test_fill_missing_days():
    # Construct a dataframe with missing dates
    records = [
        {"date": "2026-01-01", "business_id": "b1", "category": "dairy", "sales_qty": 10, "purchase_qty": 20, "waste_qty": 1, "unit": "kg"},
        {"date": "2026-01-04", "business_id": "b1", "category": "dairy", "sales_qty": 15, "purchase_qty": 0, "waste_qty": 0, "unit": "kg"},
    ]
    raw_df = pd.DataFrame(records)
    filled = fill_missing_days(raw_df)

    assert len(filled) == 4
    dates = filled["date"].tolist()
    assert dates == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
    ]
    # Check that imputed days have 0 quantity
    day_2 = filled[filled["date"] == date(2026, 1, 2)].iloc[0]
    assert day_2["sales_qty"] == 0.0


def test_category_series_has_required_features_and_daily_schema():
    records = [
        {
            "date": "2026-01-25",
            "business_id": "b1",
            "category": "dairy",
            "sales_qty": 10,
            "purchase_qty": 20,
            "waste_qty": 1,
            "unit": "kg",
        },
        {
            "date": "2026-01-26",
            "business_id": "b1",
            "category": "dairy",
            "sales_qty": 12,
            "purchase_qty": 0,
            "waste_qty": 2,
            "unit": "kg",
        },
    ]
    series = prepare_category_series(pd.DataFrame(records), "dairy", "b1")

    assert {"ds", "units_sold", "units_wasted", "day_of_week", "is_weekend", "is_indian_holiday"}.issubset(series.columns)
    assert series["units_sold"].tolist() == [10.0, 12.0]
    assert series["units_wasted"].tolist() == [1.0, 2.0]
    assert series["is_indian_holiday"].tolist() == [0, 1]


def test_handle_outliers():
    records = [
        {"date": f"2026-01-{i:02d}", "business_id": "b1", "category": "dairy", "sales_qty": 20.0, "purchase_qty": 20, "waste_qty": 1, "unit": "kg"}
        for i in range(1, 21)
    ]
    # Add a massive artificial outlier
    records.append({"date": "2026-01-21", "business_id": "b1", "category": "dairy", "sales_qty": 9999.0, "purchase_qty": 20, "waste_qty": 1, "unit": "kg"})
    df = clean_transactions(pd.DataFrame(records))
    capped = handle_outliers(df, columns=["sales_qty"], iqr_multiplier=2.5)

    assert capped["sales_qty"].max() < 100.0


def test_time_based_split_no_leakage():
    days = 100
    df = generate_synthetic_transactions(days=days, businesses=["b1"], seed=42)
    daily = prepare_category_series(df, category="bakery", business_id="b1")

    val_days = 20
    test_days = 10
    train, val, test = time_based_split(daily, val_days=val_days, test_days=test_days)

    assert len(train) == days - (val_days + test_days)
    assert len(val) == val_days
    assert len(test) == test_days

    # Zero temporal overlap
    assert train["ds"].max() < val["ds"].min()
    assert val["ds"].max() < test["ds"].min()


def test_time_based_split_defaults_to_last_30_days():
    df = generate_synthetic_transactions(days=100, businesses=["b1"], seed=42)
    daily = prepare_category_series(df, category="bakery", business_id="b1")

    train, val, test = time_based_split(daily, val_days=20)

    assert len(test) == 30
    assert len(val) == 20
    assert len(train) == 50


def test_sliding_windows_for_lstm():
    values = np.arange(50, dtype=np.float32)
    lookback = 7
    horizon = 1
    X, y = create_sliding_windows(values, lookback=lookback, horizon=horizon)

    expected_samples = 50 - lookback - horizon + 1
    assert X.shape == (expected_samples, lookback, 1)
    assert y.shape == (expected_samples, horizon)
    # Check first window
    np.testing.assert_array_equal(X[0, :, 0], values[:lookback])
    assert y[0, 0] == values[lookback]
