"""Addendum A2 end to end: negative-equity companies through the tools."""

import pytest
from mcp import Client

import main
from tests.conftest import make_statement

ENDS = ["2025-09-30", "2024-09-30", "2023-09-30"]


@pytest.fixture
def buyback(fake_yahoo):
    """Positive net income every year; equity goes negative after buybacks."""
    income = {
        "Total Revenue": [30_000.0, 28_000.0, 25_000.0],
        "Net Income": [3_000.0, 2_800.0, 2_500.0],
    }
    balance = {
        "Total Assets": [30_000.0, 29_000.0, 28_000.0],
        "Total Liabilities Net Minority Interest": [38_000.0, 30_000.0, 26_000.0],
        "Stockholders Equity": [-8_000.0, -1_000.0, 2_000.0],
        "Total Debt": [25_000.0, 22_000.0, 18_000.0],
        "Ordinary Shares Number": [1_000.0, 1_000.0, 1_000.0],
    }
    return fake_yahoo.add(
        "BUYBK",
        fast_info={"lastPrice": 100.0, "currency": "USD"},
        info={"longName": "Buyback Co", "financialCurrency": "USD"},
        statements={
            "financials": make_statement(income, ENDS),
            "balance_sheet": make_statement(balance, ENDS),
        },
    )


async def call(name, args):
    async with Client(main.mcp) as client:
        return await client.call_tool(name, args)


@pytest.mark.anyio
async def test_fundamentals_null_equity_ratios_with_notes(buyback):
    r = await call(
        "tearsheet_get_fundamentals",
        {
            "ticker": "BUYBK",
            "metrics": [
                "roe",
                "debt_to_equity",
                "liabilities_to_equity",
                "book_value_per_share",
                "roa",
            ],
        },
    )
    out = r.structured_content
    by_end = {p["period_end"]: p["metrics"] for p in out["periods"]}
    for end in ("2025-09-30", "2024-09-30"):
        assert by_end[end]["roe"] is None
        assert by_end[end]["debt_to_equity"] is None
        assert by_end[end]["liabilities_to_equity"] is None
        assert by_end[end]["book_value_per_share"] < 0
        assert by_end[end]["roa"] is not None
    assert (
        by_end["2023-09-30"]["roe"] == 1.25
        and by_end["2023-09-30"]["debt_to_equity"] == 9.0
    )
    assert out["inputs_used"]["2025-09-30"]["stockholders_equity"] == -8_000.0
    assert (
        "roe: undefined because stockholders' equity is zero or negative "
        "(-8,000 to -1,000). (periods: 2025-09-30, 2024-09-30)" in out["notes"]
    )
    assert any(n.startswith("book_value_per_share is negative") for n in out["notes"])


@pytest.mark.anyio
async def test_plot_shows_null_periods_with_the_reason(buyback, chart_dir):
    r = await call("tearsheet_plot_fundamental", {"ticker": "BUYBK", "metric": "roe"})
    assert not r.is_error, r.content[0].text
    out = r.structured_content
    # The two newest years are null at the end of the series, so A5 trims them.
    assert [v["value"] for v in out["metric_values"]] == [1.25]
    assert "Not plotted, no roe value: 2024-09-30, 2025-09-30." in out["summary"]
    assert (
        "undefined because stockholders' equity is zero or negative" in out["summary"]
    )


@pytest.mark.anyio
async def test_plot_keeps_middle_null_as_na(buyback, fake_yahoo):
    bs = fake_yahoo.symbols["BUYBK"].statements["balance_sheet"]
    bs.loc["Stockholders Equity"] = [2_400.0, -1_000.0, 2_000.0]  # middle year negative
    r = await call("tearsheet_plot_fundamental", {"ticker": "BUYBK", "metric": "roe"})
    out = r.structured_content
    assert [v["value"] for v in out["metric_values"]] == [1.25, None, 1.25]
    assert "Not plotted" not in out["summary"]
    assert "(-1,000)" in out["summary"]


@pytest.mark.anyio
async def test_plot_all_null_explains_why(buyback, fake_yahoo):
    sym = fake_yahoo.symbols["BUYBK"]
    sym.statements["balance_sheet"].loc["Stockholders Equity"] = [
        -8_000.0,
        -1_000.0,
        -500.0,
    ]
    r = await call("tearsheet_plot_fundamental", {"ticker": "BUYBK", "metric": "roe"})
    assert r.is_error
    assert "no value in any period" in r.content[0].text
    assert "zero or negative" in r.content[0].text
