import math

import numpy as np
import pandas as pd
import pytest

from tearsheet.analysis import indicators as ind
from tearsheet.data.market import normalize_history
from tests.conftest import make_ohlcv


def frame(closes) -> pd.DataFrame:
    return normalize_history(make_ohlcv(closes))


def zigzag(n=120, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return frame(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))


def test_volatility_is_annualized_daily_std():
    df = zigzag()
    vol = ind.volatility(df, 20)["volatility"]
    daily = df["close"].pct_change().rolling(20).std()
    # Old code returned the daily std; the fix multiplies by sqrt(252).
    assert vol.iloc[-1] == pytest.approx(daily.iloc[-1] * math.sqrt(252))
    assert vol.iloc[-1] > 5 * daily.iloc[-1]


def test_volatility_scales_by_interval_and_rejects_intraday():
    df = zigzag()
    weekly = ind.volatility(df, 20, "1wk")["volatility"].iloc[-1]
    daily = ind.volatility(df, 20, "1d")["volatility"].iloc[-1]
    assert weekly == pytest.approx(daily * math.sqrt(52 / 252))
    with pytest.raises(ValueError):
        ind.volatility(df, 20, "1h")


def test_macd_uses_fast_slow_signal():
    df = zigzag()
    a = ind.macd(df, 12, 26, 9)
    b = ind.macd(df, 5, 35, 5)
    assert list(a.columns) == ["macd", "signal", "histogram"]
    assert a["macd"].iloc[-1] != pytest.approx(b["macd"].iloc[-1])
    assert (a["histogram"] - (a["macd"] - a["signal"])).abs().max() < 1e-12
    assert a["macd"].iloc[:25].isna().all() and not math.isnan(a["macd"].iloc[25])


def test_macd_ignores_window():
    df = zigzag()
    pd.testing.assert_frame_equal(
        ind.compute(df, "macd", window=5), ind.compute(df, "macd", window=50)
    )


def test_rsi_all_gains_is_100_not_inf():
    out = ind.rsi(frame(np.arange(1, 41, dtype=float)), 14)["rsi"]
    assert out.iloc[:14].isna().all()
    assert (out.iloc[14:] == 100.0).all()


def test_rsi_flat_is_50_and_bounded():
    assert (ind.rsi(frame([10.0] * 30), 14)["rsi"].iloc[14:] == 50.0).all()
    out = ind.rsi(zigzag(), 14)["rsi"].dropna()
    assert out.between(0, 100).all()


def test_bollinger_num_std():
    df = zigzag()
    two = ind.bollinger_bands(df, 20, 2.0)
    three = ind.bollinger_bands(df, 20, 3.0)
    width2 = (two["upper"] - two["middle"]).iloc[-1]
    width3 = (three["upper"] - three["middle"]).iloc[-1]
    assert width3 == pytest.approx(width2 * 1.5)


def test_atr_uses_real_high_low():
    df = frame([100.0] * 30)
    df["high"], df["low"] = 102.0, 99.0  # constant 3-point range, no gaps
    out = ind.atr(df, 14)["atr"]
    assert out.iloc[:13].isna().all()
    assert out.iloc[-1] == pytest.approx(3.0)


def test_stochastic_bounds_and_d_is_smoothed_k():
    out = ind.stochastic(zigzag(), 14)
    k = out["k"].dropna()
    assert k.between(0, 100).all()
    assert out["d"].iloc[-1] == pytest.approx(out["k"].iloc[-3:].mean())


@pytest.mark.parametrize(
    "name",
    ["sma", "ema", "rsi", "macd", "volatility", "bollinger_bands", "atr", "stochastic"],
)
def test_every_indicator_runs(name):
    out = ind.compute(zigzag(), name, window=10)
    assert len(out) == 120 and out.notna().any().all()
