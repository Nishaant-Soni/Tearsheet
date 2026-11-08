from datetime import date, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

from tearsheet.models import Interval, Ticker, Tickers, Window, resolve_range

TODAY = date(2026, 11, 8)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("aapl", "AAPL"),
        ("  brk-b ", "BRK-B"),
        ("^gspc", "^GSPC"),
        ("btc-usd", "BTC-USD"),
        ("EURUSD=X", "EURUSD=X"),
        ("BRK.B", "BRK.B"),
    ],
)
def test_ticker_normalized(raw, expected):
    assert TypeAdapter(Ticker).validate_python(raw) == expected


@pytest.mark.parametrize("raw", ["", "AAPL$", "A" * 16, "AA PL", "../x"])
def test_ticker_rejected(raw):
    with pytest.raises(ValidationError):
        TypeAdapter(Ticker).validate_python(raw)


def test_tickers_length_bounds():
    adapter = TypeAdapter(Tickers)
    with pytest.raises(ValidationError):
        adapter.validate_python([])
    with pytest.raises(ValidationError):
        adapter.validate_python([f"T{i}" for i in range(11)])
    assert adapter.validate_python(["msft"]) == ["MSFT"]


def test_interval_literal():
    adapter = TypeAdapter(Interval)
    assert adapter.validate_python("1h") == "1h"
    with pytest.raises(ValidationError):
        adapter.validate_python("2h")


def test_window_bounds():
    adapter = TypeAdapter(Window)
    with pytest.raises(ValidationError):
        adapter.validate_python(1)
    with pytest.raises(ValidationError):
        adapter.validate_python(501)


def test_end_defaults_to_today():
    rng = resolve_range(date(2026, 1, 2), None, today=TODAY)
    assert rng.end == TODAY


def test_start_must_precede_end():
    with pytest.raises(ToolError, match="must be before"):
        resolve_range(date(2024, 2, 1), date(2024, 1, 1), today=TODAY)
    with pytest.raises(ToolError, match="must be before"):
        resolve_range(date(2024, 1, 1), date(2024, 1, 1), today=TODAY)


def test_future_start_rejected():
    with pytest.raises(ToolError, match="in the future"):
        resolve_range(TODAY + timedelta(days=1), None, today=TODAY)


def test_daily_allows_long_ranges():
    rng = resolve_range(date(1990, 1, 1), date(2024, 1, 1), "1d", today=TODAY)
    assert rng.start == date(1990, 1, 1)


def test_one_minute_span_limit():
    with pytest.raises(ToolError, match="at most 7 days"):
        resolve_range(TODAY - timedelta(days=10), TODAY, "1m", today=TODAY)
    resolve_range(TODAY - timedelta(days=7), TODAY, "1m", today=TODAY)


def test_one_minute_lookback_limit():
    start = TODAY - timedelta(days=40)
    with pytest.raises(ToolError, match="only goes back 30 days"):
        resolve_range(start, start + timedelta(days=5), "1m", today=TODAY)


@pytest.mark.parametrize("interval", ["5m", "15m", "30m"])
def test_sub_hourly_lookback_limit(interval):
    with pytest.raises(ToolError, match="only goes back 60 days"):
        resolve_range(TODAY - timedelta(days=61), TODAY, interval, today=TODAY)
    resolve_range(TODAY - timedelta(days=59), TODAY, interval, today=TODAY)


def test_hourly_lookback_limit():
    with pytest.raises(ToolError, match="only goes back 730 days"):
        resolve_range(TODAY - timedelta(days=800), TODAY, "1h", today=TODAY)
    resolve_range(TODAY - timedelta(days=700), TODAY, "1h", today=TODAY)
