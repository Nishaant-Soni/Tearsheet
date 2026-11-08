"""Repo-level guards: no dynamic code execution, blocking work stays off the loop."""

import re
import threading
from pathlib import Path

import numpy as np
import pytest
from mcp import Client

import main
from tests.conftest import make_ohlcv

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = [ROOT / "tearsheet", ROOT / "evals"]
SOURCE_FILES = [ROOT / "main.py", ROOT / "server.py"]


def source_files():
    for d in SOURCE_DIRS:
        yield from d.rglob("*.py")
    yield from SOURCE_FILES


def test_no_eval_or_exec_in_source():
    pattern = re.compile(r"(?<![\w.])(eval|exec)\(")
    offenders = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in source_files()
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


@pytest.mark.anyio
async def test_yfinance_calls_run_off_the_event_loop(fake_yahoo):
    fake_yahoo.add("WAVE", history=make_ohlcv(100 + np.sin(np.arange(60))))
    async with Client(main.mcp) as client:
        r = await client.call_tool(
            "tearsheet_get_price_history",
            {"tickers": ["WAVE"], "start_date": "2024-01-01"},
        )
    assert not r.is_error
    loop_thread = threading.main_thread().name
    assert fake_yahoo.history_calls
    assert all(c["thread"] != loop_thread for c in fake_yahoo.history_calls)


@pytest.mark.anyio
async def test_chart_rendering_runs_off_the_event_loop(fake_yahoo, monkeypatch):
    from tearsheet.viz import charts

    fake_yahoo.add("WAVE", history=make_ohlcv(100 + np.sin(np.arange(60))))
    threads = []
    original = charts.price_chart

    def recording(*args, **kwargs):
        threads.append(threading.current_thread().name)
        return original(*args, **kwargs)

    monkeypatch.setattr(charts, "price_chart", recording)
    async with Client(main.mcp) as client:
        r = await client.call_tool(
            "tearsheet_plot_price_chart", {"ticker": "WAVE", "start_date": "2024-01-01"}
        )
    assert not r.is_error
    assert threads and threads[0] != threading.main_thread().name
