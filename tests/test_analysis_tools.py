"""Indicator, growth and backtest tools end to end on fake prices."""

import numpy as np
import pytest
from mcp import Client

import main
from tests.conftest import make_ohlcv


async def call(name: str, args: dict):
    async with Client(main.mcp) as client:
        return await client.call_tool(name, args)


@pytest.fixture
def wave(fake_yahoo):
    t = np.arange(200)
    return fake_yahoo.add("WAVE", history=make_ohlcv(100 + 10 * np.sin(t / 8)))


@pytest.mark.anyio
async def test_indicator_summary_and_rows(wave):
    args = {
        "ticker": "WAVE",
        "indicator": "bollinger_bands",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "window": 20,
    }
    r = await call("tearsheet_calculate_indicator", args)
    out = r.structured_content
    assert set(out["summary"]) == {"upper", "middle", "lower"}
    assert out["rows"] is None and out["params"] == {"window": 20, "num_std": 2.0}
    r = await call(
        "tearsheet_calculate_indicator",
        {**args, "response_format": "rows", "max_rows": 10},
    )
    out = r.structured_content
    assert len(out["rows"]) == 10 and out["truncated"]
    assert set(out["rows"][0]) == {"date", "close", "upper", "middle", "lower"}


@pytest.mark.anyio
async def test_indicator_input_errors(wave):
    base = {"ticker": "WAVE", "start_date": "2024-01-01", "end_date": "2024-12-31"}
    r = await call(
        "tearsheet_calculate_indicator",
        {**base, "indicator": "macd", "fast": 30, "slow": 26},
    )
    assert r.is_error and "fast < slow" in r.content[0].text
    r = await call("tearsheet_calculate_indicator", {**base, "indicator": "obv"})
    assert r.is_error


@pytest.mark.anyio
async def test_backtest_tool_output_shape(wave):
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {
            "ticker": "WAVE",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "short_window": 5,
            "long_window": 20,
        },
    )
    assert not r.is_error
    out = r.structured_content
    assert out["num_trades"] >= 1 and out["bars"] == 200
    trade = out["trades"][0]
    assert set(trade) == {
        "signal_date",
        "entry_date",
        "entry_price",
        "exit_signal_date",
        "exit_date",
        "exit_price",
        "return",
        "open_at_end",
    }
    assert trade["entry_date"] > trade["signal_date"]
    assert out["buy_signal_dates"][0] == trade["signal_date"]
    assert out["max_drawdown"] <= 0


@pytest.mark.anyio
async def test_backtest_tool_errors(wave):
    base = {"ticker": "WAVE", "start_date": "2024-01-01", "end_date": "2024-12-31"}
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {**base, "short_window": 20, "long_window": 20},
    )
    assert r.is_error and "greater than short_window" in r.content[0].text
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {**base, "end_date": "2024-01-20", "long_window": 50, "short_window": 10},
    )
    assert r.is_error and "need at least 52" in r.content[0].text


@pytest.mark.anyio
async def test_growth_tool_is_pure_compute():
    async with Client(main.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        r = await client.call_tool(
            "tearsheet_calculate_growth_rates", {"values": [-50, 100]}
        )
    assert (
        tools["tearsheet_calculate_growth_rates"].annotations.open_world_hint is False
    )
    assert r.structured_content["cagr"] is None and r.structured_content["notes"]
