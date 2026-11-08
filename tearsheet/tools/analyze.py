from server import mcp
from tearsheet.analysis.backtest import backtest_strategy
from tearsheet.analysis.growth import calculate_growth_rates
from tearsheet.analysis.indicators import calculate_technical_indicators
from tearsheet.analysis.ratios import calculate_financial_metric


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
                Use retrieve_stock_data to obtain this data first.
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


@mcp.tool()
def mcp_calculate_financial_metrics(financial_data: dict, indicator: str) -> dict:
    """
    Calculates financial metrics from the provided data. The metrics are:
    - gross_margin (need retrieve income_statement)
    - operating_margin (need retrieve income_statement)
    - net_profit_margin (need retrieve income_statement)
    - ebitda (need retrieve income_statement)
    - debt_to_equity (need retrieve balance_sheet)
    - current_ratio (need retrieve balance_sheet)
    - quick_ratio (need retrieve balance_sheet)
    - book_value_per_share (need retrieve balance_sheet)
    - free_cash_flow (need retrieve cash_flow)
    - cash_flow_margin (need retrieve cash_flow)
    - roe (need retrieve income_statement and balance_sheet)
    - roa (need retrieve income_statement and balance_sheet)
    - pe_ratio (need retrieve income_statement and market)
    - pb_ratio (need retrieve income_statement and market)
    - dividend_yield (need retrieve income_statement and market)
    Args:
        financial_data: Dict with financial data.
        indicator: str, one of the supported metric names
        window: int, window size for the indicator
    Returns:
        Dict with financial metrics name as key and value as value. e.g. {'gross_margin': 0.5}
    """
    return calculate_financial_metric(financial_data, indicator)
