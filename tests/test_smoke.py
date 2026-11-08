"""Smoke tests: the server imports and registers the expected tool set."""

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
    "tearsheet_calculate_growth_rates",
    "tearsheet_calculate_indicator",
    "tearsheet_backtest_ma_crossover",
    "tearsheet_plot_price_chart",
    "tearsheet_plot_fundamental",
    "tearsheet_plot_comparison",
    "tearsheet_plot_ma_crossover",
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
