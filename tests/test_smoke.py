"""Smoke tests: the server imports and registers the expected tool set."""

import json

import pytest
from mcp import Client

import main

EXPECTED_TOOLS = {
    "tearsheet_get_quote",
    "tearsheet_get_price_history",
    "tearsheet_get_company_info",
    "tearsheet_get_dividends",
    "tearsheet_get_splits",
    "tearsheet_get_financial_statement",
    "tearsheet_get_fundamentals",
    "mcp_calculate_growth_rates",
    "mcp_calculate_technical_indicators",
    "mcp_backtest_strategy",
    "mcp_plot_price_chart",
    "mcp_plot_financial_metric",
    "mcp_plot_comparison_chart",
    "mcp_plot_trading_opportunities",
}


@pytest.mark.anyio
async def test_expected_tools_registered():
    async with Client(main.mcp) as client:
        result = await client.list_tools()
    assert {t.name for t in result.tools} == EXPECTED_TOOLS


def test_charts_use_non_gui_backend():
    # Tools run in worker threads; a GUI backend aborts the process on macOS.
    import matplotlib

    import tearsheet.viz.charts  # noqa: F401

    assert matplotlib.get_backend().lower() == "agg"


@pytest.mark.anyio
async def test_growth_rates_tool_runs_offline():
    async with Client(main.mcp) as client:
        result = await client.call_tool(
            "mcp_calculate_growth_rates", {"series": [100, 110, 121]}
        )
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["period_growth_rates"] == pytest.approx([0.1, 0.1])
    assert payload["annualized_growth_rate"] == pytest.approx(0.1)
