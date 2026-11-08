"""Optional live checks against Yahoo Finance. Skipped by default.

Run with: uv run pytest -m live
Values come from fixed historical windows (the eval questions), so they are stable.
"""

import pytest
from mcp import Client

import main

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def call(name: str, args: dict) -> dict:
    async with Client(main.mcp) as client:
        r = await client.call_tool(name, args)
    assert not r.is_error, r.content[0].text
    return r.structured_content


async def test_quote_and_history():
    q = await call("tearsheet_get_quote", {"ticker": "AAPL"})
    assert q["last_price"] > 0 and q["currency"] == "USD"
    h = await call(
        "tearsheet_get_price_history",
        {"tickers": ["MSFT"], "start_date": "2023-01-01", "end_date": "2023-12-31"},
    )
    assert h["results"][0]["summary"]["last_date"] == "2023-12-29"


async def test_splits_eval_q1():
    s = await call("tearsheet_get_splits", {"ticker": "CMG"})
    assert {"date": "2024-06-26", "value": 50.0} in s["splits"]


async def test_backtest_signal_dates_eval_q4():
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {
            "ticker": "GOOGL",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "short_window": 20,
            "long_window": 50,
        },
    )
    assert r["buy_signal_dates"][0] == "2023-03-27"


async def test_fundamentals_eval_q8():
    r = await call(
        "tearsheet_get_fundamentals", {"ticker": "AAPL", "metrics": ["debt_to_equity"]}
    )
    fy2025 = next(p for p in r["periods"] if p["period_end"].startswith("2025"))
    assert round(fy2025["metrics"]["debt_to_equity"], 2) == 1.34
