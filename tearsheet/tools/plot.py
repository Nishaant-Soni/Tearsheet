from collections.abc import Callable
from functools import partial
from typing import Annotated

import anyio
import pandas as pd
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from server import PLOT_LOCAL_WRITE, mcp
from tearsheet.analysis import backtest
from tearsheet.analysis.ratios import CURRENCY_METRICS, METRIC_UNITS
from tearsheet.data import market
from tearsheet.data.warmup import get_history_with_warmup
from tearsheet.models import (
    ChartResult,
    ChartType,
    ComparisonTickers,
    EndDate,
    EntryMode,
    LongWindow,
    Normalized,
    Period,
    PeriodValue,
    PlotMetric,
    ShortWindow,
    StartDate,
    Ticker,
    Title,
    resolve_range,
)
from tearsheet.serialize import RATIO_DP, fmt_date, num, summarize
from tearsheet.tools.common import load_fundamentals
from tearsheet.viz import charts, storage

ChartOutput = Annotated[CallToolResult, ChartResult]


async def _render_and_save(
    render: Callable[[], bytes],
    tool: str,
    tickers: list[str],
    start: str | None,
    end: str | None,
) -> tuple[bytes, str]:
    """Render in a worker thread, save under the data dir, optionally open."""

    def work() -> tuple[bytes, str]:
        png = render()
        path = storage.save_chart(png, tool, tickers, start, end)
        storage.maybe_open(path)
        return png, str(path)

    try:
        return await anyio.to_thread.run_sync(work)
    except OSError as exc:
        raise ToolError(
            f"Could not save the chart ({type(exc).__name__}). Set TEARSHEET_DATA_DIR "
            "to a writable folder."
        ) from None


def _respond(png: bytes, result: ChartResult) -> CallToolResult:
    return CallToolResult(
        content=[
            Image(data=png, format="png").to_image_content(),
            TextContent(type="text", text=result.summary),
        ],
        structured_content=result.model_dump(mode="json"),
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


@mcp.tool(name="tearsheet_plot_price_chart", annotations=PLOT_LOCAL_WRITE)
async def plot_price_chart(
    ticker: Ticker,
    start_date: StartDate,
    end_date: EndDate = None,
    chart_type: ChartType = "line",
    title: Title = None,
) -> ChartOutput:
    """Plot daily prices for one ticker as a line (closes) or candlestick chart.

    For the numbers without a chart use tearsheet_get_price_history.
    Data is fetched on the server (adjusted daily bars). Candlesticks include a
    volume panel. The PNG is saved under TEARSHEET_DATA_DIR with a server-chosen
    name and returned as an image, with a text summary (file path, date range,
    last close, period return) you can quote without reading the image.

    Example: {"ticker": "AAPL", "start_date": "2024-01-01", "chart_type": "candlestick"}
    """
    rng = resolve_range(start_date, end_date, "1d")
    df = await market.get_history(ticker, rng.start, rng.end, "1d")
    s = summarize(df)
    png, path = await _render_and_save(
        partial(charts.price_chart, df, ticker, chart_type, title),
        "price_chart",
        [ticker],
        s.first_date,
        s.last_date,
    )
    text = (
        f"{chart_type.capitalize()} chart of {ticker}, {s.first_date} to {s.last_date} "
        f"({s.rows} bars). Last close {s.last_close}, period return "
        f"{_pct(s.period_return)}. Saved to {path}."
    )
    return _respond(
        png,
        ChartResult(
            chart="price_chart",
            file_path=path,
            tickers=[ticker],
            start_date=s.first_date,
            end_date=s.last_date,
            summary=text,
            price_summaries={ticker: s},
        ),
    )


@mcp.tool(name="tearsheet_plot_comparison", annotations=PLOT_LOCAL_WRITE)
async def plot_comparison(
    tickers: ComparisonTickers,
    start_date: StartDate,
    end_date: EndDate = None,
    normalized: Normalized = True,
    title: Title = None,
) -> ChartOutput:
    """Plot daily closes for 2 to 8 tickers on one chart.

    For period returns without a chart use tearsheet_get_price_history.
    normalized=true (default) rebases each series to 100 at its first close in the
    range, so tickers at different price levels compare directly; false plots raw
    closes. Saves the PNG under TEARSHEET_DATA_DIR and returns it with a text
    summary of each ticker's period return.

    Example: {"tickers": ["NVDA", "AMD", "INTC"], "start_date": "2024-01-01"}
    """
    rng = resolve_range(start_date, end_date, "1d")
    unique = list(dict.fromkeys(tickers))
    frames = await market.gather(
        *(partial(market.get_history, t, rng.start, rng.end, "1d") for t in unique)
    )
    closes = pd.concat(
        {t: df["close"] for t, df in zip(unique, frames)}, axis=1
    ).sort_index()
    summaries = {t: summarize(df) for t, df in zip(unique, frames)}
    start, end = fmt_date(closes.index[0]), fmt_date(closes.index[-1])
    png, path = await _render_and_save(
        partial(charts.comparison_chart, closes, normalized, title),
        "comparison",
        unique,
        start,
        end,
    )
    returns = ", ".join(f"{t} {_pct(s.period_return)}" for t, s in summaries.items())
    text = (
        f"{'Normalized (base 100)' if normalized else 'Raw close'} comparison, {start} to "
        f"{end}. Period returns: {returns}. Saved to {path}."
    )
    return _respond(
        png,
        ChartResult(
            chart="comparison",
            file_path=path,
            tickers=unique,
            start_date=start,
            end_date=end,
            summary=text,
            price_summaries=summaries,
        ),
    )


@mcp.tool(name="tearsheet_plot_fundamental", annotations=PLOT_LOCAL_WRITE)
async def plot_fundamental(
    ticker: Ticker, metric: PlotMetric, period: Period = "annual"
) -> ChartOutput:
    """Plot one financial metric across fiscal periods as a bar chart.

    Uses the same definitions as tearsheet_get_fundamentals (ratios as fractions,
    shown as percentages; ebitda and free_cash_flow in the reporting currency).
    Price-based ratios (pe_ratio, pb_ratio, dividend_yield) exist only for the
    latest period and cannot be plotted. roe, debt_to_equity and
    liabilities_to_equity are null when stockholders' equity is <= 0; null periods
    are drawn as "n/a" bars and the summary gives the reason. Returns the image plus
    the plotted values.

    Example: {"ticker": "MSFT", "metric": "free_cash_flow", "period": "annual"}
    """
    data = await load_fundamentals(ticker, period, [metric])
    dp = 0 if metric in CURRENCY_METRICS else RATIO_DP
    points = [
        (end, num(values[metric], dp)) for end, values in reversed(data.table.periods)
    ]
    reasons = [n for n in data.table.notes if n.startswith(metric)]
    if all(v is None for _, v in points):
        raise ToolError(
            f"{metric} has no value in any period for '{ticker}'. "
            + (" ".join(reasons) or "Yahoo does not report its inputs.")
        )
    unit = METRIC_UNITS[metric]
    png, path = await _render_and_save(
        partial(charts.fundamental_chart, points, ticker, metric, unit, data.currency),
        f"fundamental_{metric}",
        [ticker],
        points[0][0],
        points[-1][0],
    )
    listed = ", ".join(f"{end}: {v}" for end, v in points)
    currency = data.currency or "reporting currency"
    unit_text = {
        "percent": "fraction, 0.25 = 25%",
        "multiple": "times",
        "amount": currency,
        "per_share": f"{currency} per share",
    }[unit]
    notes = "".join(f" {n}" for n in reasons)
    text = (
        f"{ticker} {metric} ({period}, {unit_text}): {listed}.{notes} Saved to {path}."
    )
    return _respond(
        png,
        ChartResult(
            chart="fundamental",
            file_path=path,
            tickers=[ticker],
            start_date=points[0][0],
            end_date=points[-1][0],
            summary=text,
            metric_values=[PeriodValue(period_end=e, value=v) for e, v in points],
        ),
    )


@mcp.tool(name="tearsheet_plot_ma_crossover", annotations=PLOT_LOCAL_WRITE)
async def plot_ma_crossover(
    ticker: Ticker,
    start_date: StartDate,
    end_date: EndDate = None,
    short_window: ShortWindow = 9,
    long_window: LongWindow = 21,
    entry_mode: EntryMode = "crossover",
    title: Title = None,
) -> ChartOutput:
    """Plot closes with short/long SMAs and mark crossover buy/sell signals.

    Uses the same warm-up and signal computation as tearsheet_backtest_ma_crossover
    (same inputs give the same signal dates): SMAs include long_window+1 bars before
    start_date, only the requested range is drawn, and markers sit at the signal
    bar's close. A signal on the last warm-up bar is listed in the summary but not
    drawn. Use the backtest tool for returns.

    Example: {"ticker": "TSLA", "start_date": "2024-01-01", "short_window": 20,
              "long_window": 50}
    """
    if long_window <= short_window:
        raise ToolError(
            f"long_window ({long_window}) must be greater than short_window ({short_window})."
        )
    rng = resolve_range(start_date, end_date, "1d")
    hist = await get_history_with_warmup(
        ticker, rng.start, rng.end, "1d", True, long_window + 1
    )
    if len(hist.df) < long_window:
        raise ToolError(
            f"Only {len(hist.df)} daily bars up to {rng.end}, including warm-up; need "
            f"at least {long_window} for long_window={long_window}. Use a shorter "
            "long_window or a later end_date."
        )
    bt = backtest.backtest_ma_crossover(
        hist.df,
        short_window,
        long_window,
        cost_bps=0.0,
        first_in_range=hist.first_in_range,
        entry_mode=entry_mode,
    )
    buys = [fmt_date(d) for d in bt.buy_signals]
    sells = [fmt_date(d) for d in bt.sell_signals]
    s = summarize(hist.in_range)
    png, path = await _render_and_save(
        partial(
            charts.ma_crossover_chart,
            hist.df,
            ticker,
            short_window,
            long_window,
            title,
            hist.first_in_range,
            bt.buy_signals,
            bt.sell_signals,
        ),
        "ma_crossover",
        [ticker],
        s.first_date,
        s.last_date,
    )
    notes = "".join(f" {n}" for n in hist.notes)
    text = (
        f"{ticker} SMA {short_window}/{long_window} ({entry_mode}), {s.first_date} to "
        f"{s.last_date}. {len(buys)} buy signals ({', '.join(buys) or 'none'}), "
        f"{len(sells)} sell signals ({', '.join(sells) or 'none'}). Last close "
        f"{s.last_close}.{notes} Saved to {path}."
    )
    return _respond(
        png,
        ChartResult(
            chart="ma_crossover",
            file_path=path,
            tickers=[ticker],
            start_date=s.first_date,
            end_date=s.last_date,
            summary=text,
            price_summaries={ticker: s},
            buy_signal_dates=buys,
            sell_signal_dates=sells,
        ),
    )
