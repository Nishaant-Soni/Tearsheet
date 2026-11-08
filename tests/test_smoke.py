"""Phase 0 smoke tests: the restructured server still exposes the original tools."""

import json

import pytest
from mcp import Client

import main

ORIGINAL_TOOLS = {
    "retrieve_current_price",
    "retrieve_stock_data",
    "retrieve_dividends",
    "retrieve_splits",
    "retrieve_ticker_info",
    "retrieve_financial_statements",
    "mcp_calculate_growth_rates",
    "mcp_calculate_technical_indicators",
    "mcp_backtest_strategy",
    "mcp_calculate_financial_metrics",
    "mcp_plot_price_chart",
    "mcp_plot_financial_metric",
    "mcp_plot_comparison_chart",
    "mcp_plot_trading_opportunities",
}


@pytest.mark.anyio
async def test_original_tools_registered():
    async with Client(main.mcp) as client:
        result = await client.list_tools()
    assert {t.name for t in result.tools} == ORIGINAL_TOOLS


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
