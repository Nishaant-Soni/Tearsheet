"""Price history with extra bars before the requested start ("warm-up").

Moving averages and recursive indicators need history before the first day the
caller asked about. These helpers fetch it, keep at most the bars needed, and say in
notes when less was available (new listings, Yahoo's intraday lookback limits).
The caller's own [start, end] range is validated separately and exactly as before;
the warm-up span never triggers a range error the caller's range would not.
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from tearsheet.data import market
from tearsheet.errors import NoDataError, no_data_in_range
from tearsheet.models import INTRADAY_INTERVALS, INTRADAY_LIMITS

# Bars in a 6.5-hour regular session.
BARS_PER_TRADING_DAY = {"1m": 390, "5m": 78, "15m": 26, "30m": 13, "1h": 7}


@dataclass
class WarmupHistory:
    df: pd.DataFrame  # warm-up bars followed by every bar in [start, end]
    first_in_range: int  # df.iloc[first_in_range] is the first bar on or after start
    warmup_requested: int
    notes: list[str] = field(default_factory=list)

    @property
    def warmup_bars_used(self) -> int:
        return self.first_in_range

    @property
    def warmup_start(self) -> pd.Timestamp | None:
        return self.df.index[0] if self.first_in_range else None

    @property
    def in_range(self) -> pd.DataFrame:
        return self.df.iloc[self.first_in_range :]


def warmup_calendar_days(interval: str, bars: int) -> int:
    """Calendar days to fetch before start to cover `bars` bars, with margin."""
    if bars <= 0:
        return 0
    if interval == "1d":
        return math.ceil(bars * 1.6) + 10
    if interval == "1wk":
        return bars * 7 + 14
    if interval == "1mo":
        return bars * 31 + 31
    trading_days = math.ceil(bars / BARS_PER_TRADING_DAY[interval])
    return math.ceil(trading_days * 1.6) + 3


async def get_history_with_warmup(
    ticker: str,
    start: date,
    end: date,
    interval: str,
    adjusted: bool,
    warmup_bars: int,
    today: date | None = None,
) -> WarmupHistory:
    """Up to `warmup_bars` bars before `start` plus all bars in [start, end].

    One get_history call covers the whole span, so repeated requests hit the cache.
    """
    today = today or date.today()
    notes: list[str] = []
    fetch_start = start - timedelta(days=warmup_calendar_days(interval, warmup_bars))
    if interval in INTRADAY_LIMITS:
        # Same limits resolve_range enforces on the caller's range, and never later
        # than the caller's own start, so warm-up cannot cause a new range error.
        max_span, max_lookback = INTRADAY_LIMITS[interval]
        floor = today - timedelta(days=max_lookback)
        if max_span is not None:
            floor = max(floor, end - timedelta(days=max_span))
        floor = min(floor, start)
        if fetch_start < floor:
            fetch_start = floor
            notes.append(f"Warm-up limited by Yahoo's {interval} history window.")

    try:
        df = await market.get_history(ticker, fetch_start, end, interval, adjusted)
    except NoDataError:
        raise no_data_in_range(ticker, str(start), str(end), interval) from None

    first = int(df.index.searchsorted(pd.Timestamp(start), side="left"))
    if first >= len(df):
        raise no_data_in_range(ticker, str(start), str(end), interval)
    keep_from = max(0, first - warmup_bars)
    df = df.iloc[keep_from:]
    first -= keep_from
    if first < warmup_bars:
        when = (
            f" (history starts {df.index[0].date()})"
            if first and interval not in INTRADAY_INTERVALS
            else ""
        )
        notes.append(
            f"Only {first} of {warmup_bars} warm-up bars were available before "
            f"{start}{when}; the first values in range use less history."
        )
    return WarmupHistory(df, first, warmup_bars, notes)
