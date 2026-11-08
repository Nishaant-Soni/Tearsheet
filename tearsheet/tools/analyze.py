from datetime import date, timedelta
from functools import partial
from typing import Annotated

from pydantic import Field

from server import READ_ONLY_REMOTE, mcp
from tearsheet.analysis.backtest import backtest_strategy
from tearsheet.analysis.growth import calculate_growth_rates
from tearsheet.analysis.indicators import calculate_technical_indicators
from tearsheet.analysis.ratios import (
    ALL_METRICS,
    CURRENCY_METRICS,
    MARKET_METRICS,
    METRIC_FIELDS,
    MarketInputs,
    compute_fundamentals,
    ttm_eps,
)
from tearsheet.data import fundamentals, market
from tearsheet.data.fundamentals import FIELD_STATEMENT, LABELS
from tearsheet.models import (
    AsOfPrice,
    FundamentalMetric,
    FundamentalsPeriod,
    FundamentalsResult,
    Period,
    Ticker,
)
from tearsheet.serialize import RATIO_DP, num


@mcp.tool()
def mcp_calculate_growth_rates(series: list) -> dict:
    """
    Calculates growth rates for a time series (e.g., revenue, earnings).
    Args:
        series: List of numbers ordered oldest to newest.
    Returns:
        Dict with annualized growth rate and list of period-over-period growth rates.
    """
    return calculate_growth_rates(series)


@mcp.tool()
def mcp_calculate_technical_indicators(
    price_data: list, indicator: str, window: int = 14
) -> dict:
    """
    Calculates technical indicators on stock price data.
    Args:
        price_data: List of closing prices (numbers) OR list of OHLCV dicts with keys
                    'open', 'high', 'low', 'close'. The OHLCV dict form is required for
                    'atr' and 'stochastic'; either form works for all others.
        indicator: One of:
                   'sma'            – Simple Moving Average
                   'ema'            – Exponential Moving Average
                   'rsi'            – Relative Strength Index (Wilder's smoothing)
                   'macd'           – MACD line + signal line
                   'volatility'     – Rolling annualised volatility
                   'bollinger_bands'– Upper / middle / lower bands (2-sigma)
                   'atr'            – Average True Range (needs OHLCV dicts)
                   'stochastic'     – Stochastic %K and %D (needs OHLCV dicts)
        window: Lookback window (default 14).
    Returns:
        Dict with indicator values as lists.
    """
    return calculate_technical_indicators(price_data, indicator, window)


@mcp.tool()
def mcp_backtest_strategy(
    prices: list, short_window: int = 9, long_window: int = 21
) -> dict:
    """
    Backtests a moving-average crossover strategy (Golden Cross / Death Cross) on historical prices.
    Buy signal: short MA crosses above long MA. Sell signal: short MA crosses below long MA.
    Args:
        prices: List of OHLCV dicts with at least 'date' and 'close' keys.
                Use tearsheet_get_price_history with response_format='rows' first.
        short_window: Short MA period (default 9).
        long_window:  Long MA period (default 21).
    Returns:
        Dict with:
          total_return        – Strategy compound return over the period
          buy_and_hold_return – Passive return over the same period
          outperformance      – total_return minus buy_and_hold_return
          num_trades          – Number of completed round-trip trades
          win_rate            – Fraction of trades that were profitable
          max_drawdown        – Worst peak-to-trough loss on the equity curve
          sharpe_ratio        – Return / std-dev of per-trade returns (approximate)
          trades              – List of individual buy/sell records with dates and P&L
    """
    return backtest_strategy(prices, short_window, long_window)


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

    pe_ratio, pb_ratio and dividend_yield use the current price (as_of_price) and
    fill only the latest period. pe_ratio uses latest annual diluted EPS (TTM for
    quarterly) and is null when EPS <= 0. dividend_yield = trailing 12 months of
    dividends / price. inputs_used lists the inputs per period; notes explain
    fallbacks and nulls.

    Example: {"ticker": "AAPL", "metrics": ["gross_margin", "debt_to_equity"]}
    """
    wanted = list(dict.fromkeys(metrics or ALL_METRICS))
    statements = sorted(
        {FIELD_STATEMENT[f] for m in wanted for f in METRIC_FIELDS[m]},
        key=list(LABELS).index,
    )
    market_wanted = [m for m in wanted if m in MARKET_METRICS]

    periods, currency = [], None
    if statements:
        (periods, notes), currency = await market.gather(
            partial(fundamentals.get_merged_fields, ticker, period, statements),
            partial(fundamentals.get_financial_currency, ticker),
        )
    else:
        notes = []

    as_of, inputs = None, None
    if market_wanted:
        quote, dividends = await market.gather(
            partial(market.get_quote, ticker),
            partial(market.get_dividends, ticker, date.today() - timedelta(days=365)),
        )
        eps, eps_note = ttm_eps(periods, period)
        mismatch = None
        if currency and quote.currency and currency != quote.currency:
            mismatch = (
                f"pe_ratio and pb_ratio: statements are in {currency} but the price "
                f"is in {quote.currency}, so they are not computed."
            )
        inputs = MarketInputs(
            price=quote.last_price,
            eps=eps,
            eps_note=eps_note,
            ttm_dividends=sum(d.value for d in dividends),
            currency_mismatch=mismatch,
        )
        if not periods:
            periods = [(date.today().isoformat(), {})]
        as_of = AsOfPrice(
            price=quote.last_price,
            currency=quote.currency,
            fetched_at=quote.fetched_at,
            applies_to_period_end=periods[0][0],
        )

    table = compute_fundamentals(periods, wanted, inputs)
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
    return FundamentalsResult(
        ticker=ticker,
        currency=currency,
        period=period,
        as_of_price=as_of,
        periods=rows,
        inputs_used={
            end: {k: num(v) for k, v in used.items()}
            for end, used in table.inputs_used.items()
            if end in kept
        },
        notes=[*notes, *table.notes],
    )
