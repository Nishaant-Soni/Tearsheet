"""yfinance access for prices, quotes, company info, dividends and splits.

This is the only layer (with data/fundamentals.py) that calls yfinance. Every call
runs in a worker thread via anyio so it never blocks the event loop, and failures
surface as ToolError with a next step.

Price histories use a timezone-naive DatetimeIndex named `date` (exchange local
time) and lowercase columns: open, high, low, close, volume.
"""

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import Any, TypeVar

import anyio
import pandas as pd
import yfinance as yf
from mcp.server.mcpserver.exceptions import ToolError

from tearsheet.data.cache import DAILY_TTL, INTRADAY_TTL, TTLCache
from tearsheet.errors import (
    no_data_in_range,
    ticker_not_found,
    upstream_failure,
)
from tearsheet.models import (
    INTRADAY_INTERVALS,
    CompanyInfo,
    DatedValue,
    Quote,
)
from tearsheet.serialize import integer, num

T = TypeVar("T")

HISTORY_COLUMNS = ["open", "high", "low", "close", "volume"]
SUGGESTABLE_TYPES = {
    "EQUITY",
    "ETF",
    "INDEX",
    "MUTUALFUND",
    "CURRENCY",
    "CRYPTOCURRENCY",
}

_history_cache = TTLCache()
_actions_cache = TTLCache()


async def run_yf(what: str, fn: Callable[[], T]) -> T:
    """Run a blocking yfinance call in a thread, mapping unexpected errors."""
    try:
        return await anyio.to_thread.run_sync(fn)
    except Exception as exc:
        if type(exc).__name__ in ("YFTzMissingError", "YFTickerMissingError"):
            raise ticker_not_found(what) from None
        raise upstream_failure(what, exc) from None


async def gather(*calls: Callable[[], Awaitable[Any]]) -> list[Any]:
    """Run async calls concurrently. Re-raises the first ToolError by call order.

    Errors are collected instead of escaping the task group, so the client gets the
    actionable ToolError message rather than an ExceptionGroup.
    """
    results: list[Any] = [None] * len(calls)
    errors: list[BaseException | None] = [None] * len(calls)

    async def run(i: int) -> None:
        try:
            results[i] = await calls[i]()
        except Exception as exc:
            errors[i] = exc

    async with anyio.create_task_group() as tg:
        for i in range(len(calls)):
            tg.start_soon(run, i)
    tool_errors = [e for e in errors if isinstance(e, ToolError)]
    if len(tool_errors) > 1:
        raise ToolError(" ".join(dict.fromkeys(str(e) for e in tool_errors)))
    for e in errors:
        if e is not None:
            raise e
    return results


def _suggest(ticker: str) -> list[str]:
    """Up to 3 alternative symbols from yf.Search. Best effort, never raises."""
    candidates: list[str] = []
    if "." in ticker:
        candidates.append(ticker.replace(".", "-"))
    try:
        quotes = yf.Search(ticker, max_results=8, news_count=0).quotes
    except Exception:
        quotes = []
    for q in quotes:
        symbol = q.get("symbol")
        if symbol and q.get("quoteType") in SUGGESTABLE_TYPES:
            candidates.append(symbol)
    seen: list[str] = []
    for c in candidates:
        if c != ticker and c not in seen:
            seen.append(c)
    return seen[:3]


def ticker_exists(ticker: str) -> bool:
    try:
        return num(yf.Ticker(ticker).fast_info["lastPrice"]) is not None
    except Exception:
        return False


async def raise_not_found(ticker: str) -> None:
    suggestions = await anyio.to_thread.run_sync(partial(_suggest, ticker))
    raise ticker_not_found(ticker, suggestions)


# ----------------------------------------------------------------- history


def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=str.lower)
    df = df[[c for c in HISTORY_COLUMNS if c in df.columns]]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "date"
    return df.dropna(how="all").sort_index()


def _download_history(
    ticker: str, start: date, end: date, interval: str, adjusted: bool
) -> pd.DataFrame:
    raw = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
        interval=interval,
        auto_adjust=adjusted,
        actions=False,
    )
    return normalize_history(raw)


async def get_history(
    ticker: str, start: date, end: date, interval: str = "1d", adjusted: bool = True
) -> pd.DataFrame:
    """OHLCV bars for [start, end] inclusive. Raises ToolError if empty.

    adjusted=True adjusts for splits and dividends. adjusted=False is yfinance's raw
    close, which is still split-adjusted but not dividend-adjusted.
    """
    intraday = interval in INTRADAY_INTERVALS
    ttl = INTRADAY_TTL if intraday or end >= date.today() else DAILY_TTL

    async def load() -> pd.DataFrame:
        df = await run_yf(
            ticker, partial(_download_history, ticker, start, end, interval, adjusted)
        )
        if df.empty:
            exists = await anyio.to_thread.run_sync(partial(ticker_exists, ticker))
            if not exists:
                await raise_not_found(ticker)
            raise no_data_in_range(ticker, str(start), str(end), interval)
        return df

    key = ("history", ticker, start, end, interval, adjusted)
    return await _history_cache.get_or_load(key, ttl, load)


# ------------------------------------------------------------ quote / info


def _read_quote(ticker: str) -> Quote:
    fi = yf.Ticker(ticker).fast_info
    try:
        last = num(fi["lastPrice"])
    except KeyError:
        last = None
    if last is None:
        raise LookupError(ticker)

    def field(key: str) -> Any:
        try:
            return fi[key]
        except Exception:
            return None

    prev = num(field("previousClose"))
    change = num(last - prev) if prev is not None else None
    return Quote(
        ticker=ticker,
        last_price=last,
        previous_close=prev,
        change=change,
        change_pct=num(change / prev) if change is not None and prev else None,
        currency=field("currency"),
        market_cap=num(field("marketCap"), 0),
        shares_outstanding=num(field("shares"), 0),
        exchange=field("exchange"),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


async def get_quote(ticker: str) -> Quote:
    """Latest price from Ticker.fast_info (does not call the slow .info endpoint)."""
    try:
        return await anyio.to_thread.run_sync(partial(_read_quote, ticker))
    except LookupError:
        await raise_not_found(ticker)
        raise  # unreachable, keeps type checkers happy
    except Exception as exc:
        raise upstream_failure(ticker, exc) from None


async def get_company_info(ticker: str) -> CompanyInfo:
    info: dict = await run_yf(ticker, lambda: yf.Ticker(ticker).info or {})
    name = info.get("longName") or info.get("shortName")
    if not name and not info.get("quoteType"):
        await raise_not_found(ticker)
    return CompanyInfo(
        ticker=ticker,
        name=name,
        quote_type=info.get("quoteType"),
        exchange=info.get("fullExchangeName") or info.get("exchange"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        currency=info.get("currency"),
        country=info.get("country"),
        website=info.get("website"),
        employees=integer(info.get("fullTimeEmployees")),
    )


# ------------------------------------------------------- dividends / splits


def _series_to_events(series: pd.Series) -> list[DatedValue]:
    if series.empty:
        return []
    idx = series.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    # yfinance >= 1.x stamps actions at market open (09:30); keep the date only.
    series = pd.Series(series.to_numpy(), index=pd.DatetimeIndex(idx).normalize())
    return [
        DatedValue(date=ts.strftime("%Y-%m-%d"), value=float(v))
        for ts, v in series.sort_index().items()
        if num(v) is not None
    ]


async def _get_actions(ticker: str, kind: str) -> list[DatedValue]:
    async def load() -> list[DatedValue]:
        series = await run_yf(ticker, lambda: getattr(yf.Ticker(ticker), kind))
        events = _series_to_events(series)
        if not events:
            exists = await anyio.to_thread.run_sync(partial(ticker_exists, ticker))
            if not exists:
                await raise_not_found(ticker)
        return events

    return await _actions_cache.get_or_load((kind, ticker), DAILY_TTL, load)


async def get_dividends(ticker: str, start: date | None = None) -> list[DatedValue]:
    """Cash dividends per share by ex-date, oldest first. Empty for non-payers."""
    events = await _get_actions(ticker, "dividends")
    if start is not None:
        events = [e for e in events if e.date >= start.isoformat()]
    return events


async def get_splits(ticker: str) -> list[DatedValue]:
    """Split ratios (new shares per old share) by date, oldest first."""
    return await _get_actions(ticker, "splits")


def clear_caches() -> None:
    _history_cache.clear()
    _actions_cache.clear()
