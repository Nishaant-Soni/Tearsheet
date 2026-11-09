"""Addendum A1: warm-up bars for moving averages, indicators and the crossover plot."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from mcp import Client

import main
from tearsheet.analysis import indicators as ind
from tearsheet.analysis.backtest import backtest_ma_crossover, crossover_signals
from tearsheet.data.market import normalize_history
from tearsheet.data.warmup import get_history_with_warmup, warmup_calendar_days
from tests.conftest import EXCHANGE_TZ, make_ohlcv

SHORT, LONG = 10, 50


async def call(name: str, args: dict):
    async with Client(main.mcp) as client:
        r = await client.call_tool(name, args)
    assert not r.is_error, r.content[0].text
    return r.structured_content


def v_shape(n_down=150, n_up=150, start="2020-01-02") -> pd.DataFrame:
    """Falls 200 -> 100, then rises back: one golden cross a few bars after the low."""
    closes = np.r_[np.linspace(200, 100, n_down), np.linspace(100, 200, n_up)]
    return make_ohlcv(closes, start=start)


def day(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


@pytest.mark.anyio
async def test_missed_early_cross_is_caught(fake_yahoo):
    raw = v_shape()
    fake_yahoo.add("VEE", history=raw)
    idx = normalize_history(raw).index
    k = int(
        np.flatnonzero(
            crossover_signals(normalize_history(raw)["close"], SHORT, LONG)["signal"]
            == 1
        )[0]
    )
    start = idx[k - 5]  # the cross lands on in-range bar 5
    assert k - 5 > LONG + 1

    r = await call(
        "tearsheet_backtest_ma_crossover",
        {
            "ticker": "VEE",
            "start_date": day(start),
            "end_date": day(idx[-1]),
            "short_window": SHORT,
            "long_window": LONG,
        },
    )
    assert r["trades"][0]["signal_date"] == day(idx[k])
    assert r["warmup_bars_used"] == LONG + 1 and r["bars"] == len(idx) - (k - 5)

    # Without warm-up (the old behavior) the 50-day MA is not ready at bar 5.
    cold = backtest_ma_crossover(normalize_history(raw).iloc[k - 5 :], SHORT, LONG, 0)
    assert idx[k] not in [t.signal_date for t in cold.trades]


@pytest.mark.anyio
async def test_results_do_not_depend_on_how_much_extra_history_exists(fake_yahoo):
    raw = make_ohlcv(100 + 15 * np.sin(np.arange(900) / 17), start="2018-01-01")
    idx = normalize_history(raw).index
    start_pos = 600  # well over two years of bars before start
    fake_yahoo.add("LONGHIST", history=raw)
    fake_yahoo.add("EXACT", history=raw.iloc[start_pos - (LONG + 1) :])
    args = {
        "start_date": day(idx[start_pos]),
        "end_date": day(idx[-1]),
        "short_window": SHORT,
        "long_window": LONG,
    }
    a = await call("tearsheet_backtest_ma_crossover", {"ticker": "LONGHIST", **args})
    b = await call("tearsheet_backtest_ma_crossover", {"ticker": "EXACT", **args})
    del a["ticker"], b["ticker"]
    assert a == b
    assert a["trades"], "the series should trade, or the comparison proves little"


@pytest.mark.parametrize(
    "name, w", [("ema", 14), ("rsi", 14), ("atr", 14), ("ema", 50), ("rsi", 50)]
)
def test_recursive_indicators_forget_their_seed(name, w):
    rng = np.random.default_rng(7)
    df = normalize_history(
        make_ohlcv(100 * np.cumprod(1 + rng.normal(0, 0.02, 2500)), start="2010-01-04")
    )
    start = len(df) - 200
    used = ind.warmup_bars(name, w)
    ours = ind.compute(df.iloc[start - used :], name, window=w).iloc[used:]
    reference = ind.compute(df.iloc[start - 20 * w :], name, window=w).iloc[20 * w :]
    assert (ours - reference).abs().max().max() < 1e-3


def test_macd_warmup_forgets_its_seed():
    rng = np.random.default_rng(8)
    df = normalize_history(
        make_ohlcv(100 * np.cumprod(1 + rng.normal(0, 0.02, 2000)), start="2010-01-04")
    )
    start, used = len(df) - 200, ind.warmup_bars("macd", 14, 26, 9)
    ours = ind.macd(df.iloc[start - used :]).iloc[used:]
    reference = ind.macd(df.iloc[start - 600 :]).iloc[600:]
    assert (ours - reference).abs().max().max() < 1e-3


@pytest.mark.anyio
async def test_state_mode_enters_at_first_in_range_open(fake_yahoo):
    raw = make_ohlcv(
        np.linspace(50, 150, 300), start="2021-01-04"
    )  # short > long throughout
    fake_yahoo.add("UP", history=raw)
    df = normalize_history(raw)
    first = 120
    args = {
        "ticker": "UP",
        "start_date": day(df.index[first]),
        "end_date": day(df.index[-1]),
        "short_window": SHORT,
        "long_window": LONG,
    }

    crossover = await call("tearsheet_backtest_ma_crossover", args)
    assert crossover["trades"] == [] and crossover["exposure"] == 0

    state = await call(
        "tearsheet_backtest_ma_crossover", {**args, "entry_mode": "state"}
    )
    t = state["trades"][0]
    assert t["entry_date"] == day(df.index[first])
    assert t["entry_price"] == pytest.approx(df["open"].iloc[first], abs=1e-4)
    assert t["signal_date"] == day(df.index[first - 1])  # last warm-up bar
    assert state["entry_mode"] == "state" and state["exposure"] == 1.0


@pytest.mark.anyio
async def test_buy_and_hold_is_first_in_range_open_to_last_close(fake_yahoo):
    raw = v_shape()
    fake_yahoo.add("VEE", history=raw)
    df = normalize_history(raw)
    first = 100
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {
            "ticker": "VEE",
            "start_date": day(df.index[first]),
            "end_date": day(df.index[-1]),
            "short_window": SHORT,
            "long_window": LONG,
        },
    )
    expected = df["close"].iloc[-1] / df["open"].iloc[first] - 1
    assert r["buy_and_hold_return"] == pytest.approx(expected, abs=1e-4)


@pytest.mark.anyio
async def test_short_warmup_history_is_a_note_not_an_error(fake_yahoo):
    raw = v_shape()
    fake_yahoo.add("NEW", history=raw)
    df = normalize_history(raw)
    r = await call(
        "tearsheet_backtest_ma_crossover",
        {
            "ticker": "NEW",
            "start_date": day(df.index[10]),
            "end_date": day(df.index[-1]),
            "short_window": SHORT,
            "long_window": LONG,
        },
    )
    assert r["warmup_bars_used"] == 10
    assert any("Only 10 of 51 warm-up bars" in n for n in r["notes"])


@pytest.mark.anyio
@pytest.mark.parametrize("entry_mode", ["crossover", "state"])
async def test_plot_and_backtest_report_the_same_signals(fake_yahoo, entry_mode):
    raw = make_ohlcv(100 + 15 * np.sin(np.arange(500) / 11), start="2019-01-02")
    fake_yahoo.add("WAVE", history=raw)
    df = normalize_history(raw)
    args = {
        "ticker": "WAVE",
        "start_date": day(df.index[200]),
        "end_date": day(df.index[-1]),
        "short_window": SHORT,
        "long_window": LONG,
        "entry_mode": entry_mode,
    }
    bt = await call("tearsheet_backtest_ma_crossover", args)
    plot = await call("tearsheet_plot_ma_crossover", args)
    assert bt["buy_signal_dates"] and bt["sell_signal_dates"]
    assert plot["buy_signal_dates"] == bt["buy_signal_dates"]
    assert plot["sell_signal_dates"] == bt["sell_signal_dates"]
    for d in bt["buy_signal_dates"]:
        assert d in plot["summary"]


def intraday_frame(first_day: date, last_day: date) -> pd.DataFrame:
    days = pd.bdate_range(first_day, last_day)
    stamps = [d + pd.Timedelta(minutes=570 + 5 * i) for d in days for i in range(78)]
    idx = pd.DatetimeIndex(stamps).tz_localize(EXCHANGE_TZ)
    closes = 100 + np.sin(np.arange(len(idx)) / 50)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 0.1,
            "Low": closes - 0.1,
            "Close": closes,
            "Volume": 10,
        },
        index=idx,
    )


@pytest.mark.anyio
async def test_intraday_warmup_is_clamped_not_rejected(fake_yahoo):
    today = date.today()
    fake_yahoo.add("INTRA", history=intraday_frame(today - timedelta(days=90), today))
    start = today - timedelta(days=59)
    # 600 bars of warm-up would reach back past Yahoo's 60-day limit for 5m.
    assert start - timedelta(days=warmup_calendar_days("5m", 600)) < today - timedelta(
        days=60
    )
    hist = await get_history_with_warmup("INTRA", start, today, "5m", True, 600)
    assert (
        fake_yahoo.history_calls[-1]["start"]
        == (today - timedelta(days=60)).isoformat()
    )
    assert any("Warm-up limited" in n for n in hist.notes)
    assert hist.df.index[hist.first_in_range] >= pd.Timestamp(start)

    r = await call(
        "tearsheet_calculate_indicator",
        {
            "ticker": "INTRA",
            "indicator": "rsi",
            "interval": "5m",
            "start_date": start.isoformat(),
            "window": 50,
        },
    )
    assert r["summary"]["rsi"]["latest"] is not None


@pytest.mark.anyio
async def test_indicator_values_start_on_the_first_in_range_day(fake_yahoo):
    raw = v_shape()
    fake_yahoo.add("VEE", history=raw)
    df = normalize_history(raw)
    first = 200
    args = {
        "ticker": "VEE",
        "start_date": day(df.index[first]),
        "end_date": day(df.index[-1]),
        "response_format": "rows",
        "max_rows": 1000,
    }
    for name, extra in [
        ("sma", {}),
        ("rsi", {}),
        ("stochastic", {}),
        ("volatility", {}),
        ("macd", {}),
        ("bollinger_bands", {}),
    ]:
        r = await call(
            "tearsheet_calculate_indicator",
            {**args, "indicator": name, "window": 20, **extra},
        )
        first_row = r["rows"][0]
        assert first_row["date"] == day(df.index[first]), name
        assert all(v is not None for k, v in first_row.items() if k != "date"), (
            name,
            first_row,
        )
        assert r["total_rows"] == len(df) - first
        assert r["warmup_bars_used"] == min(first, ind.warmup_bars(name, 20))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "start, end",
    [
        ("2023-01-01", "2023-06-30"),  # nothing in warm-up span or range
        ("2021-03-01", "2021-03-31"),  # warm-up bars exist, the range itself is empty
    ],
)
async def test_no_bars_in_range_reports_the_callers_dates(fake_yahoo, start, end):
    fake_yahoo.add(
        "VEE", history=v_shape(), fast_info={"lastPrice": 150.0}
    )  # ends 2021-02
    async with Client(main.mcp) as client:
        r = await client.call_tool(
            "tearsheet_backtest_ma_crossover",
            {
                "ticker": "VEE",
                "start_date": start,
                "end_date": end,
                "short_window": SHORT,
                "long_window": LONG,
            },
        )
    assert r.is_error
    text = r.content[0].text
    assert f"between {start} and {end}" in text and "Widen the date range" in text
