import numpy as np
import pandas as pd
import pytest

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


# ---- addendum A3: share count fallback

END = "2025-06-30"


def shares(rows: dict) -> tuple[float | None, list[str], list[str]]:
    df = make_statement({"Total Assets": [1_000.0], **rows}, [END])
    ns = normalize_statement(df, "balance_sheet", "annual")
    return ns.periods[0].fields["shares_outstanding"], ns.notes, ns.unmapped_labels


def test_ordinary_shares_used_first():
    value, notes, unmapped = shares(
        {
            "Ordinary Shares Number": [700.0],
            "Share Issued": [1_000.0],
            "Treasury Shares Number": [300.0],
        }
    )
    assert value == 700.0 and notes == []
    # Issued/treasury are not used here, so they stay visible as unmapped.
    assert "Share Issued" in unmapped and "Treasury Shares Number" in unmapped


def test_issued_minus_treasury_when_ordinary_missing():
    value, notes, unmapped = shares(
        {"Share Issued": [1_000.0], "Treasury Shares Number": [300.0]}
    )
    assert value == 700.0  # not the issued count
    assert notes == [
        f"{END}: shares_outstanding derived as shares issued minus treasury shares."
    ]
    assert "Share Issued" not in unmapped and "Treasury Shares Number" not in unmapped


@pytest.mark.parametrize("treasury_rows", [{}, {"Treasury Shares Number": [np.nan]}])
def test_issued_alone_when_no_treasury_reported(treasury_rows):
    # Deviation from the addendum (which says None): Yahoo omits the treasury line for
    # companies that hold no treasury shares, where issued == ordinary.
    value, notes, _ = shares({"Share Issued": [1_000.0], **treasury_rows})
    assert value == 1_000.0
    assert notes == [
        f"{END}: shares_outstanding taken from shares issued; Yahoo reports no treasury "
        "shares for this period."
    ]


def test_no_share_count_is_none_with_note():
    value, notes, _ = shares({"Treasury Shares Number": [300.0]})
    assert value is None
    assert notes == [
        f"{END}: shares_outstanding not reported (no ordinary or issued share count)."
    ]


def test_book_value_per_share_uses_derived_count():
    from tearsheet.analysis.ratios import STATEMENT_METRICS

    df = make_statement(
        {
            "Stockholders Equity": [7_000.0],
            "Share Issued": [1_000.0],
            "Treasury Shares Number": [300.0],
        },
        [END],
    )
    fields = normalize_statement(df, "balance_sheet", "annual").periods[0].fields
    # 7000 / 700 = 10.0; the old issued-count fallback gave 7000 / 1000 = 7.0.
    assert STATEMENT_METRICS["book_value_per_share"](fields).value == 10.0
