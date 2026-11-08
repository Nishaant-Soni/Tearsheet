import math

import numpy as np
import pandas as pd
import pytest

from tearsheet.data.market import normalize_history
from tearsheet.serialize import clean, downsample_positions, num, summarize, to_rows
from tests.conftest import make_ohlcv


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -math.inf, np.nan, None])
def test_num_maps_non_finite_to_none(value):
    assert num(value) is None


def test_num_rounds_and_unwraps_numpy():
    out = num(np.float64(1.234567))
    assert out == 1.2346 and type(out) is float


def test_clean_is_recursive():
    data = {"a": np.nan, "b": [1.0, np.inf, np.int64(3)], "c": {"d": np.float32(0.5)}}
    assert clean(data) == {"a": None, "b": [1.0, None, 3], "c": {"d": 0.5}}


def test_downsample_keeps_endpoints_and_cap():
    pos = downsample_positions(1000, 100)
    assert len(pos) == 100
    assert pos[0] == 0 and pos[-1] == 999
    assert pos == sorted(set(pos))
    assert downsample_positions(10, 100) == list(range(10))


def test_summary_fields():
    closes = [10.0, 8.0, 12.0, 11.0]
    df = normalize_history(make_ohlcv(closes))
    s = summarize(df)
    assert s.rows == 4
    assert (s.first_date, s.last_date) == ("2024-01-02", "2024-01-05")
    assert s.first_close == 10.0 and s.last_close == 11.0
    assert s.period_return == pytest.approx(0.1)
    assert (s.min_close, s.min_close_date) == (8.0, "2024-01-03")
    assert (s.max_close, s.max_close_date) == (12.0, "2024-01-04")
    assert s.avg_volume == 1_000_000


def test_summary_handles_nan_close():
    df = normalize_history(make_ohlcv([10.0, np.nan, 12.0]))
    s = summarize(df)
    assert s.last_close == 12.0 and s.period_return == pytest.approx(0.2)


def test_rows_truncated_flag_and_nan():
    df = normalize_history(make_ohlcv(np.arange(1, 251, dtype=float)))
    df.iloc[0, df.columns.get_loc("open")] = np.nan
    rows, truncated = to_rows(df, 10)
    assert truncated and len(rows) == 10
    assert rows[0].date == "2024-01-02" and rows[0].open is None
    assert rows[-1].close == 250.0

    rows, truncated = to_rows(df, 1000)
    assert not truncated and len(rows) == 250


def test_normalize_history_tz_naive_lowercase():
    raw = make_ohlcv([1.0, 2.0])
    raw["Adj Close"] = raw["Close"]
    df = normalize_history(raw)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None and df.index.name == "date"
    assert isinstance(df.index, pd.DatetimeIndex)
