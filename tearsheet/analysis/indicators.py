"""Technical indicators as pure functions on OHLCV DataFrames.

Inputs use the data layer's frame shape: DatetimeIndex, lowercase open, high, low,
close, volume. Each function returns a DataFrame of output series on the same
index. Warm-up bars, where the indicator is not yet defined, are NaN.
"""

import math

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = {"1d": 252, "1wk": 52, "1mo": 12}


def _wilder(series: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing: recursive average with alpha = 1 / window."""
    return series.ewm(alpha=1.0 / window, adjust=False).mean()


def _mask_head(series: pd.Series, n: int) -> pd.Series:
    out = series.copy()
    out.iloc[:n] = np.nan
    return out


def sma(df: pd.DataFrame, window: int) -> pd.DataFrame:
    return pd.DataFrame({"sma": df["close"].rolling(window).mean()})


def ema(df: pd.DataFrame, window: int) -> pd.DataFrame:
    values = df["close"].ewm(span=window, adjust=False).mean()
    return pd.DataFrame({"ema": _mask_head(values, window - 1)})


def rsi(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """RSI with Wilder smoothing, 0 to 100.

    100 when the average loss is 0 (only gains), 50 when both averages are 0 (no
    price change). The first `window` values are NaN.
    """
    delta = df["close"].diff()
    avg_gain = _wilder(delta.clip(lower=0).fillna(0.0), window)
    avg_loss = _wilder((-delta).clip(lower=0).fillna(0.0), window)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = 100 - 100 / (1 + avg_gain / avg_loss)
    values = values.where(avg_loss != 0, 100.0)
    values = values.where((avg_loss != 0) | (avg_gain != 0), 50.0)
    return pd.DataFrame({"rsi": _mask_head(values, window)})


def macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    close = df["close"]
    line = (
        close.ewm(span=fast, adjust=False).mean()
        - close.ewm(span=slow, adjust=False).mean()
    )
    sig = line.ewm(span=signal, adjust=False).mean()
    line = _mask_head(line, slow - 1)
    sig = _mask_head(sig, slow + signal - 2)
    return pd.DataFrame({"macd": line, "signal": sig, "histogram": line - sig})


def volatility(df: pd.DataFrame, window: int, interval: str = "1d") -> pd.DataFrame:
    """Rolling std of simple returns, annualized (fraction: 0.25 = 25%)."""
    if interval not in PERIODS_PER_YEAR:
        raise ValueError(f"volatility is not annualized for interval '{interval}'")
    returns = df["close"].pct_change()
    values = returns.rolling(window).std() * math.sqrt(PERIODS_PER_YEAR[interval])
    return pd.DataFrame({"volatility": values})


def bollinger_bands(
    df: pd.DataFrame, window: int, num_std: float = 2.0
) -> pd.DataFrame:
    close = df["close"]
    middle = close.rolling(window).mean()
    std = close.rolling(window).std()
    return pd.DataFrame(
        {
            "upper": middle + num_std * std,
            "middle": middle,
            "lower": middle - num_std * std,
        }
    )


def atr(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Average true range with Wilder smoothing, in price units."""
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return pd.DataFrame({"atr": _mask_head(_wilder(true_range, window), window - 1)})


def stochastic(df: pd.DataFrame, window: int, smooth: int = 3) -> pd.DataFrame:
    """%K = position of close in the window's high-low range (0 to 100); %D = SMA of %K."""
    lowest = df["low"].rolling(window).min()
    highest = df["high"].rolling(window).max()
    k = 100 * (df["close"] - lowest) / (highest - lowest).replace(0, np.nan)
    return pd.DataFrame({"k": k, "d": k.rolling(smooth).mean()})


def compute(
    df: pd.DataFrame,
    indicator: str,
    window: int = 14,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    num_std: float = 2.0,
    interval: str = "1d",
) -> pd.DataFrame:
    """Dispatch by indicator name. MACD ignores `window`; the others ignore fast/slow/signal."""
    if indicator == "macd":
        return macd(df, fast, slow, signal)
    if indicator == "volatility":
        return volatility(df, window, interval)
    if indicator == "bollinger_bands":
        return bollinger_bands(df, window, num_std)
    funcs = {"sma": sma, "ema": ema, "rsi": rsi, "atr": atr, "stochastic": stochastic}
    return funcs[indicator](df, window)
