from datetime import date

import anyio
import pandas as pd
from mcp.server.mcpserver.exceptions import ToolError

from server import READ_ONLY_REMOTE, mcp
from tearsheet.data import market
from tearsheet.data.fundamentals import get_financial_statements
from tearsheet.models import (
    INTRADAY_INTERVALS,
    CompanyInfo,
    DividendsResult,
    EndDate,
    Interval,
    MaxRows,
    PriceHistoryResult,
    Quote,
    ResponseFormat,
    SplitsResult,
    StartDate,
    Ticker,
    TickerHistory,
    Tickers,
    resolve_range,
)
from tearsheet.serialize import num, summarize, to_rows


@mcp.tool(name="tearsheet_get_quote", annotations=READ_ONLY_REMOTE)
async def get_quote(ticker: Ticker) -> Quote:
    """Get the latest price, previous close and day change for one ticker.

    Use for "what is X trading at now". For prices over a date range use
    tearsheet_get_price_history.

    Returns last_price and previous_close in the quote currency, change (absolute),
    change_pct (fraction: 0.012 = +1.2%), market_cap, shares_outstanding, exchange.
    Prices may be delayed by up to 15 minutes.

    Example: {"ticker": "AAPL"}
    """
    return await market.get_quote(ticker)


@mcp.tool(name="tearsheet_get_price_history", annotations=READ_ONLY_REMOTE)
async def get_price_history(
    tickers: Tickers,
    start_date: StartDate,
    end_date: EndDate = None,
    interval: Interval = "1d",
    adjusted: bool = True,
    response_format: ResponseFormat = "summary",
    max_rows: MaxRows = 100,
) -> PriceHistoryResult:
    """Get OHLCV price history for 1 to 10 tickers over a date range.

    end_date is inclusive. Intraday limits: '1m' spans at most 7 days within the
    last 30; '5m'/'15m'/'30m' only the last 60 days; '1h' the last 730 days.
    adjusted=true (default) adjusts for splits and dividends; adjusted=false is
    split-adjusted but not dividend-adjusted.

    response_format='summary' (default) returns per ticker: rows, first/last date
    and close, period_return (fraction), min/max close with dates, avg_volume.
    response_format='rows' also returns OHLCV rows, at most max_rows per ticker;
    longer series are downsampled evenly with truncated=true and total_rows set.
    Prefer summary unless you need individual bars.

    Example: {"tickers": ["AAPL", "MSFT"], "start_date": "2024-01-01",
              "end_date": "2024-06-30"}
    """
    rng = resolve_range(start_date, end_date, interval)
    intraday = interval in INTRADAY_INTERVALS
    frames: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    async def fetch(t: str) -> None:
        try:
            frames[t] = await market.get_history(
                t, rng.start, rng.end, interval, adjusted
            )
        except ToolError as e:
            errors.append(str(e))

    async with anyio.create_task_group() as tg:
        for t in dict.fromkeys(tickers):
            tg.start_soon(fetch, t)
    if errors:
        raise ToolError(" ".join(errors))

    results = []
    for t in dict.fromkeys(tickers):
        df = frames[t]
        rows, truncated = (
            to_rows(df, max_rows, intraday)
            if response_format == "rows"
            else (None, False)
        )
        results.append(
            TickerHistory(
                ticker=t,
                summary=summarize(df, intraday),
                rows=rows,
                truncated=truncated,
                total_rows=len(df),
            )
        )
    return PriceHistoryResult(
        start_date=str(rng.start),
        end_date=str(rng.end),
        interval=interval,
        adjusted=adjusted,
        response_format=response_format,
        results=results,
    )


@mcp.tool(name="tearsheet_get_company_info", annotations=READ_ONLY_REMOTE)
async def get_company_info(ticker: Ticker) -> CompanyInfo:
    """Get descriptive info for one ticker: name, type, exchange, sector, industry.

    Use to identify a company or check what a symbol refers to. Not for prices
    (tearsheet_get_quote) or financials (tearsheet_get_financial_statement).

    Returns name, quote_type (EQUITY, ETF, ...), exchange, sector, industry,
    currency, country, website, employees. Fields Yahoo lacks are null.

    Example: {"ticker": "NVDA"}
    """
    return await market.get_company_info(ticker)


@mcp.tool(name="tearsheet_get_dividends", annotations=READ_ONLY_REMOTE)
async def get_dividends(
    ticker: Ticker, start_date: StartDate | None = None
) -> DividendsResult:
    """Get cash dividends per share by ex-date for one ticker.

    start_date (optional, YYYY-MM-DD) drops earlier dividends. Amounts are per
    share in the quote currency, adjusted for later splits. Non-payers return an
    empty list, not an error.

    Returns count, total (sum of listed amounts) and dividends: [{date, value}],
    oldest first.

    Example: {"ticker": "KO", "start_date": "2023-01-01"}
    """
    events = await market.get_dividends(ticker, start_date)
    return DividendsResult(
        ticker=ticker,
        start_date=start_date.isoformat() if isinstance(start_date, date) else None,
        count=len(events),
        total=num(sum(e.value for e in events)) or 0.0,
        dividends=events,
    )


@mcp.tool(name="tearsheet_get_splits", annotations=READ_ONLY_REMOTE)
async def get_splits(ticker: Ticker) -> SplitsResult:
    """Get the full stock split history for one ticker.

    Each value is the split ratio as new shares per old share: 10.0 is a 10-for-1
    split, 0.1 is a 1-for-10 reverse split. Tickers that never split return an
    empty list, not an error.

    Returns count and splits: [{date, value}], oldest first.

    Example: {"ticker": "NVDA"}
    """
    events = await market.get_splits(ticker)
    return SplitsResult(ticker=ticker, count=len(events), splits=events)


@mcp.tool()
def retrieve_financial_statements(ticker: str, indicator: str) -> dict:
    """
    Retrieves the annual income statements, balance sheet, or cash flow for the given ticker.
    Args:
        ticker: The ticker symbol of the stock to retrieve the statements for.
        indicator: The type of financial statement to retrieve. e.g. "income_statement", "balance_sheet", "cash_flow"
    Returns:
        A JSON-serializable dict with income statements, balance sheet, or cash flow.
    """
    return get_financial_statements(ticker, indicator)
