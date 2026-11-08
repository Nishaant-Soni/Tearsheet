"""Plot tools end to end: image + text content, structured result, safe paths."""

import os
import subprocess

import numpy as np
import pytest
from mcp import Client

import main
from tests.conftest import make_ohlcv


async def call(name: str, args: dict):
    async with Client(main.mcp) as client:
        return await client.call_tool(name, args)


@pytest.fixture
def no_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("plot tools must not spawn processes")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(os, "startfile", boom, raising=False)


@pytest.fixture
def prices(fake_yahoo):
    t = np.arange(150)
    fake_yahoo.add("WAVE", history=make_ohlcv(100 + 10 * np.sin(t / 8)))
    fake_yahoo.add("TREND", history=make_ohlcv(np.linspace(50, 80, 150)))


def assert_chart(r, chart_dir):
    assert not r.is_error, r.content[0].text
    kinds = [c.type for c in r.content]
    assert kinds == ["image", "text"]
    assert r.content[0].mime_type == "image/png" and r.content[0].data
    path = r.structured_content["file_path"]
    assert os.path.realpath(path).startswith(os.path.realpath(chart_dir))
    assert os.path.getsize(path) > 0
    assert path in r.content[1].text
    return r.structured_content


@pytest.mark.anyio
@pytest.mark.parametrize("chart_type", ["line", "candlestick"])
async def test_price_chart(prices, chart_dir, no_subprocess, chart_type):
    r = await call(
        "tearsheet_plot_price_chart",
        {
            "ticker": "WAVE",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "chart_type": chart_type,
        },
    )
    out = assert_chart(r, chart_dir)
    assert out["price_summaries"]["WAVE"]["rows"] == 150


@pytest.mark.anyio
async def test_comparison_normalized_by_default(prices, chart_dir, no_subprocess):
    r = await call(
        "tearsheet_plot_comparison",
        {
            "tickers": ["WAVE", "TREND"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    out = assert_chart(r, chart_dir)
    assert "Normalized" in out["summary"] and set(out["tickers"]) == {"WAVE", "TREND"}


@pytest.mark.anyio
async def test_comparison_needs_two_tickers(prices):
    r = await call(
        "tearsheet_plot_comparison", {"tickers": ["WAVE"], "start_date": "2024-01-01"}
    )
    assert r.is_error


@pytest.mark.anyio
async def test_ma_crossover(prices, chart_dir, no_subprocess):
    r = await call(
        "tearsheet_plot_ma_crossover",
        {
            "ticker": "WAVE",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "short_window": 5,
            "long_window": 20,
        },
    )
    out = assert_chart(r, chart_dir)
    assert out["buy_signal_dates"] and out["sell_signal_dates"]


@pytest.mark.anyio
async def test_fundamental(acme, chart_dir, no_subprocess):
    r = await call(
        "tearsheet_plot_fundamental", {"ticker": "ACME", "metric": "free_cash_flow"}
    )
    out = assert_chart(r, chart_dir)
    assert out["metric_values"] == [
        {"period_end": "2024-06-30", "value": 300.0},
        {"period_end": "2025-06-30", "value": 400.0},
    ]
    assert "(annual, USD)" in out["summary"]


@pytest.mark.anyio
async def test_fundamental_ratio_units_in_summary(acme, chart_dir, no_subprocess):
    r = await call(
        "tearsheet_plot_fundamental", {"ticker": "ACME", "metric": "debt_to_equity"}
    )
    assert "(annual, times)" in assert_chart(r, chart_dir)["summary"]
    r = await call(
        "tearsheet_plot_fundamental", {"ticker": "ACME", "metric": "net_margin"}
    )
    assert "(annual, fraction, 0.25 = 25%)" in assert_chart(r, chart_dir)["summary"]


@pytest.mark.anyio
async def test_fundamental_rejects_price_based_metric(acme):
    r = await call(
        "tearsheet_plot_fundamental", {"ticker": "ACME", "metric": "pe_ratio"}
    )
    assert r.is_error


@pytest.mark.anyio
async def test_plot_tools_have_no_filename_parameter():
    async with Client(main.mcp) as client:
        tools = [t for t in (await client.list_tools()).tools if "plot" in t.name]
    assert len(tools) == 4
    for t in tools:
        assert "filename" not in t.input_schema["properties"]
        assert (
            t.annotations.read_only_hint is False
            and t.annotations.destructive_hint is False
        )
        assert t.output_schema is not None
