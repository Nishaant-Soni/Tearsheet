"""Statement and fundamentals tools end to end on fake statements."""

import pytest
from mcp import Client

import main


async def call(name: str, args: dict):
    async with Client(main.mcp) as client:
        return await client.call_tool(name, args)


@pytest.mark.anyio
@pytest.mark.parametrize("period, n", [("annual", 2), ("quarterly", 4)])
async def test_financial_statement_annual_and_quarterly(acme, period, n):
    r = await call(
        "tearsheet_get_financial_statement",
        {"ticker": "acme", "statement": "income_statement", "period": period},
    )
    assert not r.is_error
    out = r.structured_content
    assert out["currency"] == "USD" and len(out["fiscal_periods"]) == n
    assert out["fiscal_periods"][0]["period_end"] == "2025-06-30"
    assert out["fiscal_periods"][0]["fields"]["revenue"] in (1000.0, 260.0)


@pytest.mark.anyio
async def test_financial_statement_reports_unmapped(acme):
    r = await call(
        "tearsheet_get_financial_statement",
        {"ticker": "ACME", "statement": "balance_sheet"},
    )
    assert r.structured_content["unmapped_labels"] == ["Goodwill"]


@pytest.mark.anyio
async def test_fundamentals_annual_values(acme):
    r = await call("tearsheet_get_fundamentals", {"ticker": "ACME"})
    assert not r.is_error
    out = r.structured_content
    latest = out["periods"][0]["metrics"]
    assert latest["debt_to_equity"] == 0.4  # 800 / 2000
    assert latest["liabilities_to_equity"] == 1.5
    assert latest["free_cash_flow"] == 400.0  # 500 - |-100|
    assert latest["gross_margin"] == 0.6
    assert latest["pe_ratio"] == 20.0  # 40 / 2.0
    assert latest["pb_ratio"] == 2.0  # 40 / (2000 / 100)
    assert out["periods"][1]["metrics"]["pe_ratio"] is None
    assert out["as_of_price"]["applies_to_period_end"] == "2025-06-30"
    assert out["inputs_used"]["2025-06-30"]["total_debt"] == 800.0


@pytest.mark.anyio
async def test_fundamentals_quarterly_uses_ttm_eps(acme):
    r = await call(
        "tearsheet_get_fundamentals",
        {
            "ticker": "ACME",
            "period": "quarterly",
            "metrics": ["net_margin", "pe_ratio"],
        },
    )
    out = r.structured_content
    assert out["periods"][0]["metrics"] == {"net_margin": 0.2, "pe_ratio": 20.0}
    assert any("trailing-twelve-month" in n for n in out["notes"])


@pytest.mark.anyio
async def test_fundamentals_skips_unneeded_statements(acme, fake_yahoo):
    r = await call(
        "tearsheet_get_fundamentals", {"ticker": "ACME", "metrics": ["net_margin"]}
    )
    assert r.structured_content["as_of_price"] is None
    assert set(r.structured_content["periods"][0]["metrics"]) == {"net_margin"}


@pytest.mark.anyio
async def test_fundamentals_rejects_unknown_metric(acme):
    r = await call(
        "tearsheet_get_fundamentals",
        {"ticker": "ACME", "metrics": ["net_profit_margin"]},
    )
    assert r.is_error


@pytest.mark.anyio
async def test_no_statements_is_error(fake_yahoo):
    fake_yahoo.add("SPY", fast_info={"lastPrice": 500.0})
    r = await call("tearsheet_get_fundamentals", {"ticker": "SPY"})
    assert r.is_error and "no annual income statement" in r.content[0].text
    r = await call("tearsheet_get_fundamentals", {"ticker": "ZZZZ"})
    assert r.is_error and "No data found" in r.content[0].text
