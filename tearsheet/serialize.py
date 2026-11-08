"""Turn DataFrames and numpy values into JSON-safe, rounded Python values."""

import math
from typing import Any

import numpy as np
import pandas as pd

from tearsheet.models import HistorySummary, PriceRow, SeriesSummary

PRICE_DP = 4
RATIO_DP = 4


def num(value: Any, dp: int = PRICE_DP) -> float | None:
    """Float rounded to `dp`, or None for missing, NaN and infinite values."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, dp)


def integer(value: Any) -> int | None:
    f = num(value, 0)
    return None if f is None else int(f)


def clean(obj: Any, dp: int = RATIO_DP) -> Any:
    """Recursively replace NaN/inf with None and numpy scalars with Python types."""
    if isinstance(obj, dict):
        return {k: clean(v, dp) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v, dp) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return num(obj, dp)
    return obj


def fmt_date(ts: pd.Timestamp, intraday: bool = False) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M") if intraday else ts.strftime("%Y-%m-%d")


def summarize(df: pd.DataFrame, intraday: bool = False) -> HistorySummary:
    close = df["close"].dropna()
    first = close.iloc[0] if len(close) else None
    last = close.iloc[-1] if len(close) else None
    period_return = (
        num(last / first - 1, RATIO_DP)
        if first not in (None, 0) and last is not None
        else None
    )
    return HistorySummary(
        rows=len(df),
        first_date=fmt_date(df.index[0], intraday),
        last_date=fmt_date(df.index[-1], intraday),
        first_close=num(first),
        last_close=num(last),
        period_return=period_return,
        min_close=num(close.min()) if len(close) else None,
        min_close_date=fmt_date(close.idxmin(), intraday) if len(close) else None,
        max_close=num(close.max()) if len(close) else None,
        max_close_date=fmt_date(close.idxmax(), intraday) if len(close) else None,
        avg_volume=num(df["volume"].mean(), 0),
    )


def downsample_positions(n: int, max_rows: int) -> list[int]:
    """Evenly spaced positions in range(n), always keeping the first and last."""
    if n <= max_rows:
        return list(range(n))
    if max_rows == 1:
        return [n - 1]
    return sorted({round(i * (n - 1) / (max_rows - 1)) for i in range(max_rows)})


def to_rows(
    df: pd.DataFrame, max_rows: int, intraday: bool = False
) -> tuple[list[PriceRow], bool]:
    """Row records capped at `max_rows`. Returns (rows, truncated)."""
    positions = downsample_positions(len(df), max_rows)
    rows = [
        PriceRow(
            date=fmt_date(ts, intraday),
            open=num(r.open),
            high=num(r.high),
            low=num(r.low),
            close=num(r.close),
            volume=integer(r.volume),
        )
        for ts, r in zip(df.index[positions], df.iloc[positions].itertuples())
    ]
    return rows, len(positions) < len(df)


def series_summary(series: pd.Series, intraday: bool = False) -> SeriesSummary:
    valid = series.dropna()
    if valid.empty:
        return SeriesSummary(
            latest=None,
            latest_date=None,
            min=None,
            min_date=None,
            max=None,
            max_date=None,
        )
    return SeriesSummary(
        latest=num(valid.iloc[-1]),
        latest_date=fmt_date(valid.index[-1], intraday),
        min=num(valid.min()),
        min_date=fmt_date(valid.idxmin(), intraday),
        max=num(valid.max()),
        max_date=fmt_date(valid.idxmax(), intraday),
    )


def frame_rows(
    df: pd.DataFrame, max_rows: int, intraday: bool = False
) -> tuple[list[dict[str, float | str | None]], bool]:
    """Generic row records ({date, col: value}) capped at `max_rows`."""
    positions = downsample_positions(len(df), max_rows)
    sub = df.iloc[positions]
    rows = [
        {"date": fmt_date(ts, intraday), **{c: num(v) for c, v in row.items()}}
        for ts, row in sub.iterrows()
    ]
    return rows, len(positions) < len(df)
