from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from server import PURE_COMPUTE, READ_ONLY_REMOTE, mcp
from tearsheet.analysis import backtest, growth, indicators
from tearsheet.analysis.ratios import (
    ALL_METRICS,
    CURRENCY_METRICS,
)
from tearsheet.data.warmup import get_history_with_warmup
from tearsheet.models import (
    INTRADAY_INTERVALS,
    Adjusted,
    BacktestResult,
    BacktestTrade,
    CostBps,
    EndDate,
    EntryMode,
    FastPeriod,
    FundamentalMetric,
    FundamentalsPeriod,
    FundamentalsResult,
    GrowthResult,
    Indicator,
    IndicatorResult,
    Interval,
    LongWindow,
    MaxRows,
    NumStd,
    Period,
    ResponseFormat,
    RiskFreeRate,
    ShortWindow,
    SignalPeriod,
    SlowPeriod,
    StartDate,
    Ticker,
    Window,
    resolve_range,
)
from tearsheet.serialize import RATIO_DP, frame_rows, num, series_summary
from tearsheet.tools.common import load_fundamentals


@mcp.tool(name="tearsheet_calculate_indicator", annotations=READ_ONLY_REMOTE)
async def calculate_indicator(
    ticker: Ticker,
    indicator: Indicator,
    start_date: StartDate,
    end_date: EndDate = None,
    interval: Interval = "1d",
    window: Window = 14,
    fast: FastPeriod = 12,
    slow: SlowPeriod = 26,
    signal: SignalPeriod = 9,
    num_std: NumStd = 2.0,
    response_format: ResponseFormat = "summary",
    max_rows: MaxRows = 100,
) -> IndicatorResult:
    """Compute a technical indicator for one ticker over a date range.

    For strategy returns use tearsheet_backtest_ma_crossover; for raw prices
    tearsheet_get_price_history.
    Prices are fetched on the server (adjusted closes), including warm-up bars
    before start_date so values are defined from the first day; only in-range values
    are returned. Warm-up: window bars for sma/bollinger_bands, window+2 stochastic,
    window+1 volatility; recursive smoothing needs more to forget its seed: 6x window
    for ema, 12x for rsi/atr, 5x (slow+signal) for macd. Outputs: sma, ema (price);
    rsi (0-100, Wilder; 100 if no losses); macd -> macd, signal, histogram (uses
    fast/slow/signal and ignores window); volatility (rolling std of returns,
    annualized, fraction; 1d/1wk/1mo only); bollinger_bands -> upper, middle,
    lower (num_std); atr (Wilder, price units); stochastic -> k, d (0-100).

    response_format='summary' (default) returns, per output series, the latest
    value and date plus min/max with dates. 'rows' adds {date, close, series...}
    rows capped at max_rows (evenly downsampled, truncated=true).

    Example: {"ticker": "AAPL", "indicator": "rsi", "start_date": "2023-01-01",
              "end_date": "2023-12-31", "window": 14}
    """
    rng = resolve_range(start_date, end_date, interval)
    if indicator == "volatility" and interval in INTRADAY_INTERVALS:
        raise ToolError(
            "volatility is annualized only for 1d, 1wk or 1mo bars. Use one of those "
            "intervals."
        )
    if indicator == "macd" and fast >= slow:
        raise ToolError(f"MACD needs fast < slow, got fast={fast}, slow={slow}.")
    hist = await get_history_with_warmup(
        ticker,
        rng.start,
        rng.end,
        interval,
        True,
        indicators.warmup_bars(indicator, window, slow, signal),
    )
    full = indicators.compute(
        hist.df, indicator, window, fast, slow, signal, num_std, interval
    )
    df, out = hist.in_range, full.iloc[hist.first_in_range :]
    intraday = interval in INTRADAY_INTERVALS

    if indicator == "macd":
        params = {"fast": fast, "slow": slow, "signal": signal}
    elif indicator == "bollinger_bands":
        params = {"window": window, "num_std": num_std}
    else:
        params = {"window": window}
    notes = list(hist.notes)
    if out.notna().sum().min() == 0:
        notes.append(
            f"Only {len(hist.df)} bars available including warm-up, too few for these "
            "parameters; every value is null. Use an earlier start_date."
        )
    rows, truncated = None, False
    if response_format == "rows":
        rows, truncated = frame_rows(
            out.assign(close=df["close"])[["close", *out.columns]], max_rows, intraday
        )
    return IndicatorResult(
        ticker=ticker,
        indicator=indicator,
        interval=interval,
        start_date=str(rng.start),
        end_date=str(rng.end),
        params=params,
        last_close=num(df["close"].iloc[-1]),
        summary={c: series_summary(out[c], intraday) for c in out.columns},
        response_format=response_format,
        rows=rows,
        truncated=truncated,
        total_rows=len(out),
        warmup_bars_used=hist.warmup_bars_used,
        notes=notes,
    )


@mcp.tool(name="tearsheet_calculate_growth_rates", annotations=PURE_COMPUTE)
async def calculate_growth_rates(
    values: Annotated[
        list[float],
        Field(min_length=2, max_length=200, description="Series, oldest to newest."),
    ],
    periods_per_year: Annotated[
        int, Field(ge=1, le=365, description="1 for annual values, 4 for quarterly.")
    ] = 1,
) -> GrowthResult:
    """Compute period-over-period growth and CAGR for a short series of numbers.

    Use for revenue, EPS or other values you already have (e.g. from
    tearsheet_get_financial_statement). Takes the numbers directly, oldest first.

    period_growth_rates: (curr - prev) / |prev| per step, null when prev is 0.
    cagr: (last / first) ** (periods_per_year / (n - 1)) - 1, null with a note when
    first or last is <= 0. All values are fractions (0.12 = 12%).

    Example: {"values": [60922, 130497, 215938], "periods_per_year": 1}
    """
    g = growth.calculate_growth_rates(values, periods_per_year)
    return GrowthResult(
        values=values,
        periods_per_year=periods_per_year,
        period_growth_rates=[num(r, RATIO_DP) for r in g.period_growth_rates],
        cagr=num(g.cagr, RATIO_DP),
        notes=g.notes,
    )


def _day(ts) -> str | None:
    return None if ts is None else ts.strftime("%Y-%m-%d")


@mcp.tool(name="tearsheet_backtest_ma_crossover", annotations=READ_ONLY_REMOTE)
async def backtest_ma_crossover(
    ticker: Ticker,
    start_date: StartDate,
    end_date: EndDate = None,
    short_window: ShortWindow = 9,
    long_window: LongWindow = 21,
    cost_bps: CostBps = 5.0,
    risk_free_rate: RiskFreeRate = 0.0,
    adjusted: Adjusted = True,
    entry_mode: EntryMode = "crossover",
) -> BacktestResult:
    """Backtest a long-only SMA crossover strategy on daily bars for one ticker.

    To see the signals on a chart use tearsheet_plot_ma_crossover.
    Buy when the short SMA closes above the long SMA after being at or below it;
    sell on the reverse (entry_mode='state': long whenever short > long). MAs use
    long_window+1 warm-up bars before start_date, so they are defined from day 1;
    trading and all metrics start at the first in-range bar. Signal at bar t's
    close, fill at bar t+1's open (a last-bar signal is not filled; a signal on the
    last warm-up bar fills at the first in-range open and keeps its earlier
    signal_date). Fully invested or flat; cost_bps on each entry and exit, no other
    slippage; adjusted prices by default. buy_and_hold_return runs from the first
    in-range open to the last close, without costs.

    Returns fractions: total_return, buy_and_hold_return, excess_return, cagr,
    annualized_volatility (daily std * sqrt(252)), sharpe_ratio ((mean daily -
    rf/252) / std * sqrt(252); null if no variance), max_drawdown with start/end
    dates from the daily mark-to-market curve, win_rate, avg_trade_return,
    exposure. num_trades counts completed round trips. trades list signal_date,
    entry/exit fills and return; buy_signal_dates and sell_signal_dates list every
    crossover.

    Example: {"ticker": "MSFT", "start_date": "2023-01-01", "end_date":
              "2023-12-31", "short_window": 20, "long_window": 50}
    """
    if long_window <= short_window:
        raise ToolError(
            f"long_window ({long_window}) must be greater than short_window "
            f"({short_window})."
        )
    rng = resolve_range(start_date, end_date, "1d")
    hist = await get_history_with_warmup(
        ticker, rng.start, rng.end, "1d", adjusted, long_window + 1
    )
    if len(hist.df) < long_window:
        raise ToolError(
            f"Only {len(hist.df)} daily bars up to {rng.end}, including warm-up "
            f"before {rng.start}; need at least {long_window} for "
            f"long_window={long_window}. Use a shorter long_window or a later end_date."
        )
    bt = backtest.backtest_ma_crossover(
        hist.df,
        short_window,
        long_window,
        cost_bps,
        risk_free_rate,
        hist.first_in_range,
        entry_mode,
    )
    return BacktestResult(
        ticker=ticker,
        start_date=str(rng.start),
        end_date=str(rng.end),
        bars=len(hist.in_range),
        short_window=short_window,
        long_window=long_window,
        cost_bps=cost_bps,
        risk_free_rate=risk_free_rate,
        adjusted=adjusted,
        entry_mode=entry_mode,
        warmup_bars_used=hist.warmup_bars_used,
        warmup_start=_day(hist.warmup_start),
        total_return=num(bt.total_return, RATIO_DP),
        buy_and_hold_return=num(bt.buy_and_hold_return, RATIO_DP),
        excess_return=num(bt.excess_return, RATIO_DP),
        cagr=num(bt.cagr, RATIO_DP),
        annualized_volatility=num(bt.annualized_volatility, RATIO_DP),
        sharpe_ratio=num(bt.sharpe_ratio, RATIO_DP),
        max_drawdown=num(bt.max_drawdown, RATIO_DP),
        max_drawdown_start=_day(bt.max_drawdown_start),
        max_drawdown_end=_day(bt.max_drawdown_end),
        num_trades=bt.num_trades,
        win_rate=num(bt.win_rate, RATIO_DP),
        avg_trade_return=num(bt.avg_trade_return, RATIO_DP),
        exposure=num(bt.exposure, RATIO_DP),
        trades=[
            BacktestTrade(
                signal_date=_day(t.signal_date),
                entry_date=_day(t.entry_date),
                entry_price=num(t.entry_price),
                exit_signal_date=_day(t.exit_signal_date),
                exit_date=_day(t.exit_date),
                exit_price=num(t.exit_price),
                return_=num(t.ret, RATIO_DP),
                open_at_end=t.open_at_end,
            )
            for t in bt.trades
        ],
        buy_signal_dates=[_day(d) for d in bt.buy_signals],
        sell_signal_dates=[_day(d) for d in bt.sell_signals],
        notes=[*hist.notes, *bt.notes],
    )


@mcp.tool(name="tearsheet_get_fundamentals", annotations=READ_ONLY_REMOTE)
async def get_fundamentals(
    ticker: Ticker,
    period: Period = "annual",
    metrics: Annotated[
        list[FundamentalMetric] | None,
        Field(description="Metrics to compute. Omit for all of them."),
    ] = None,
) -> FundamentalsResult:
    """Compute financial ratios per fiscal period from normalized statements.

    Use for margins, leverage, liquidity, cash flow and valuation ratios. For raw
    statement line items use tearsheet_get_financial_statement.

    Ratios are fractions (0.25 = 25%). ebitda and free_cash_flow are amounts in the
    reporting currency. Definitions: debt_to_equity = total_debt / equity;
    liabilities_to_equity = total_liabilities / equity; free_cash_flow =
    operating_cash_flow - |capex|; roe and roa use period-end equity and assets.
    Quarterly periods give per-quarter (not annualized) margins and returns.
    When stockholders' equity is <= 0, roe, debt_to_equity, liabilities_to_equity
    and pb_ratio are null with a note; book_value_per_share stays negative.

    pe_ratio, pb_ratio and dividend_yield use the current price (as_of_price) and
    each fill one period, listed in as_of_price.applies_to: pe_ratio the newest with
    diluted EPS (TTM of 4 quarters for quarterly; null when EPS <= 0), pb_ratio the
    newest with equity and shares, dividend_yield the newest. Partially reported
    periods carry a note. dividend_yield = trailing 12 months of
    dividends / price. inputs_used lists the inputs per period; notes explain
    fallbacks and nulls.

    Example: {"ticker": "AAPL", "metrics": ["gross_margin", "debt_to_equity"]}
    """
    data = await load_fundamentals(
        ticker, period, list(dict.fromkeys(metrics or ALL_METRICS))
    )
    table = data.table
    rows = [
        FundamentalsPeriod(
            period_end=end,
            metrics={
                m: num(v, 0 if m in CURRENCY_METRICS else RATIO_DP)
                for m, v in values.items()
            },
        )
        for end, values in table.periods
        if any(v is not None for v in values.values())
    ]
    kept = {r.period_end for r in rows}
    # A partly reported period newer than everything returned would otherwise vanish
    # silently ("where is FY2026?"); aged-out older columns are expected to drop off.
    left_out = [
        f"{end} left out: only partly reported so far, and none of the requested "
        "metrics has a value yet."
        for end, _ in table.periods
        if end not in kept and end in data.partial and (not kept or end > max(kept))
    ]
    return FundamentalsResult(
        ticker=ticker,
        currency=data.currency,
        period=period,
        as_of_price=data.as_of,
        periods=rows,
        inputs_used={
            end: {k: num(v) for k, v in used.items()}
            for end, used in table.inputs_used.items()
            if end in kept
        },
        notes=[*left_out, *data.notes_for(kept)],
    )
