import numpy as np
import pandas as pd

from tearsheet.data.fundamentals import LABELS, normalize_statement
from tests.conftest import make_statement


def test_labels_map_to_canonical_fields_newest_first():
    df = make_statement(
        {"Total Revenue": [100.0, 120.0], "Net Income": [10.0, 12.0]},
        ["2023-12-31", "2024-12-31"],  # oldest first on purpose
    )
    ns = normalize_statement(df, "income_statement", "annual")
    assert [p.period_end for p in ns.periods] == ["2024-12-31", "2023-12-31"]
    assert ns.periods[0].fields["revenue"] == 120.0
    assert ns.periods[0].fields["net_income"] == 12.0
    assert set(ns.periods[0].fields) == set(LABELS["income_statement"])


def test_unmapped_and_missing_reported():
    df = make_statement(
        {
            "Total Revenue": [100.0],
            "Tax Rate For Calcs": [0.21],
            "Some New Label": [1.0],
        },
        ["2024-12-31"],
    )
    ns = normalize_statement(df, "income_statement", "annual")
    assert ns.unmapped_labels == ["Some New Label", "Tax Rate For Calcs"]
    assert "gross_profit" in ns.missing_fields and "revenue" not in ns.missing_fields


def test_fallback_label_used_when_first_missing_or_nan():
    df = make_statement(
        {"Stockholders Equity": [np.nan, 50.0], "Common Stock Equity": [40.0, 49.0]},
        ["2024-12-31", "2023-12-31"],
    )
    ns = normalize_statement(df, "balance_sheet", "annual")
    assert ns.periods[0].fields["stockholders_equity"] == 40.0  # fallback
    assert ns.periods[1].fields["stockholders_equity"] == 50.0  # primary


def test_total_liabilities_derived_with_note():
    df = make_statement(
        {"Total Assets": [100.0], "Total Equity Gross Minority Interest": [30.0]},
        ["2025-01-31"],
    )
    ns = normalize_statement(df, "balance_sheet", "annual")
    assert ns.periods[0].fields["total_liabilities"] == 70.0
    assert any("derived" in n for n in ns.notes)
    assert "Total Equity Gross Minority Interest" not in ns.unmapped_labels


def test_all_nan_period_dropped():
    df = make_statement(
        {"Total Revenue": [100.0, np.nan]}, ["2024-12-31", "2020-12-31"]
    )
    ns = normalize_statement(df, "income_statement", "annual")
    assert [p.period_end for p in ns.periods] == ["2024-12-31"]


def test_epoch_like_timestamp_columns():
    # yfinance columns are Timestamps; JSON round-trips turn them into epoch ms.
    col = pd.Timestamp(1735603200000, unit="ms")  # 2024-12-31
    df = pd.DataFrame({col: [5.0]}, index=["Total Revenue"])
    ns = normalize_statement(df, "income_statement", "annual")
    assert ns.periods[0].period_end == "2024-12-31"
