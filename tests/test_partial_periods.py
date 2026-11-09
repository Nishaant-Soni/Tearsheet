"""Addendum A5: fiscal periods that only some statements report."""

import pytest
from mcp import Client

import main
from tearsheet.data.fundamentals import MergedFields
from tests.conftest import make_statement

INCOME_ENDS = ["2025-12-31", "2024-12-31"]
BALANCE_ENDS = ["2026-12-31", "2025-12-31", "2024-12-31", "2023-12-31"]


@pytest.fixture
def part(fake_yahoo):
    """Newest period filed only in the balance sheet; oldest aged out of the income one."""
    income = {
        "Total Revenue": [1_000.0, 900.0],
        "Net Income": [100.0, 90.0],
        "Diluted EPS": [2.0, 1.8],
    }
    balance = {
        "Total Assets": [5_200.0, 5_000.0, 4_800.0, 4_600.0],
        "Stockholders Equity": [2_200.0, 2_000.0, 1_900.0, 1_800.0],
        "Current Assets": [1_600.0, 1_500.0, 1_400.0, 1_300.0],
        "Current Liabilities": [1_000.0, 1_000.0, 1_000.0, 1_000.0],
        "Ordinary Shares Number": [100.0, 100.0, 100.0, 100.0],
    }
    return fake_yahoo.add(
        "PART",
        fast_info={"lastPrice": 40.0, "currency": "USD"},
        info={"longName": "Partial Co", "financialCurrency": "USD"},
        statements={
            "financials": make_statement(income, INCOME_ENDS),
            "balance_sheet": make_statement(balance, BALANCE_ENDS),
        },
    )


async def call(name, args):
    async with Client(main.mcp) as client:
        r = await client.call_tool(name, args)
    assert not r.is_error, r.content[0].text
    return r.structured_content


def test_partial_notes_wording():
    merged = MergedFields(
        periods=[("2026", {}), ("2025", {}), ("2024", {}), ("2023", {})],
        sources={
            "2026": ["balance_sheet"],
            "2025": ["income_statement", "balance_sheet"],
            "2024": ["income_statement", "balance_sheet"],
            "2023": ["balance_sheet"],
        },
        statements=["income_statement", "balance_sheet"],
        notes=[],
    )
    assert merged.partial_notes() == {
        "2026": "2026: only the balance sheet reported so far; metrics needing other "
        "statements are null.",
        "2023": "2023: only the balance sheet available from Yahoo for this period; "
        "metrics needing other statements are null.",
    }


@pytest.mark.anyio
async def test_kept_partial_period_is_explained(part):
    out = await call(
        "tearsheet_get_fundamentals",
        {"ticker": "PART", "metrics": ["net_margin", "current_ratio"]},
    )
    ends = [p["period_end"] for p in out["periods"]]
    assert ends == BALANCE_ENDS  # each has a current ratio, so none is dropped
    assert out["periods"][0]["metrics"] == {"net_margin": None, "current_ratio": 1.6}
    assert (
        "2026-12-31: only the balance sheet reported so far; metrics needing other "
        "statements are null." in out["notes"]
    )
    assert any(
        n.startswith("2023-12-31: only the balance sheet available")
        for n in out["notes"]
    )


@pytest.mark.anyio
async def test_dropped_partial_period_leaves_no_notes(part):
    out = await call(
        "tearsheet_get_fundamentals",
        {"ticker": "PART", "metrics": ["net_margin", "roe"]},
    )
    ends = [p["period_end"] for p in out["periods"]]
    assert ends == INCOME_ENDS  # balance-only periods have neither metric
    assert not any("2026-12-31" in n or "2023-12-31" in n for n in out["notes"])


@pytest.mark.anyio
async def test_plot_trims_trailing_partial_period_and_says_why(part, chart_dir):
    out = await call("tearsheet_plot_fundamental", {"ticker": "PART", "metric": "roe"})
    assert [v["period_end"] for v in out["metric_values"]] == [
        "2024-12-31",
        "2025-12-31",
    ]
    assert "Not plotted, no roe value: 2023-12-31, 2026-12-31." in out["summary"]
    assert "2026-12-31: only the balance sheet reported so far" in out["summary"]
    assert "2023-12-31: only the balance sheet available from Yahoo" in out["summary"]


@pytest.mark.anyio
async def test_market_ratios_use_newest_period_with_their_inputs(part):
    out = await call(
        "tearsheet_get_fundamentals",
        {"ticker": "PART", "metrics": ["pe_ratio", "pb_ratio", "dividend_yield"]},
    )
    by_end = {p["period_end"]: p["metrics"] for p in out["periods"]}
    # P/E from the newest EPS (2025), P/B from the newest balance sheet (2026).
    assert by_end["2025-12-31"]["pe_ratio"] == 20.0
    assert by_end["2026-12-31"]["pb_ratio"] == pytest.approx(40.0 / 22.0, abs=1e-4)
    assert out["as_of_price"]["applies_to"] == {
        "pe_ratio": "2025-12-31",
        "pb_ratio": "2026-12-31",
        "dividend_yield": "2026-12-31",
    }
    assert out["as_of_price"]["applies_to_period_end"] == "2026-12-31"
    assert any(
        "pe_ratio uses 2025-12-31, the newest period that reports diluted EPS" in n
        for n in out["notes"]
    )
