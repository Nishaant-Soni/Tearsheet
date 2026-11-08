import pandas as pd


def calculate_trading_opportunities(
    prices: pd.DataFrame, short_window: int, long_window: int
) -> pd.DataFrame:
    """
    Calculates trading opportunities from price data. Create signals based on crossovers:
    - A 'Golden Cross' (bullish signal) occurs when the short-term MA crosses above the long-term MA.
    - A 'Death Cross' (bearish signal) occurs when the short-term MA crosses below the long-term MA.
    Args:
        prices: List of dicts with OHLCV and date.
        short_window: Short window for the short moving average.
        long_window: Long window for the long moving average.
    Returns:
        pd.DataFrame with trading opportunities.
    """
    prices["short_ma"] = prices["close"].rolling(window=short_window).mean()
    prices["long_ma"] = prices["close"].rolling(window=long_window).mean()
    prices["prev_short"] = prices["short_ma"].shift(1)
    prices["prev_long"] = prices["long_ma"].shift(1)
    prices["signal"] = 0
    prices.loc[
        (prices["short_ma"] > prices["long_ma"])
        & (prices["prev_short"] <= prices["prev_long"]),
        "signal",
    ] = 1
    prices.loc[
        (prices["short_ma"] < prices["long_ma"])
        & (prices["prev_short"] >= prices["prev_long"]),
        "signal",
    ] = -1
    return prices


def backtest_strategy(
    prices: list, short_window: int = 9, long_window: int = 21
) -> dict:
    """
    Backtests a moving-average crossover strategy (Golden/Death Cross) on historical prices.
    Args:
        prices: List of dicts with keys 'date', 'close' (and optionally 'open','high','low','volume').
        short_window: Short MA window.
        long_window: Long MA window.
    Returns:
        Dict with total_return, buy_and_hold_return, num_trades, win_rate, max_drawdown,
        sharpe_ratio, and a list of individual trade records.
    """
    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])
    df = calculate_trading_opportunities(df, short_window, long_window)

    position = 0
    entry_price = 0.0
    trades = []

    for _, row in df.iterrows():
        if row["signal"] == 1 and position == 0:
            position = 1
            entry_price = row["close"]
            trades.append(
                {"type": "buy", "date": str(row["date"].date()), "price": entry_price}
            )
        elif row["signal"] == -1 and position == 1:
            position = 0
            pnl = (row["close"] - entry_price) / entry_price
            trades.append(
                {
                    "type": "sell",
                    "date": str(row["date"].date()),
                    "price": row["close"],
                    "pnl": round(pnl, 4),
                }
            )

    if position == 1:
        pnl = (df.iloc[-1]["close"] - entry_price) / entry_price
        trades.append(
            {
                "type": "sell",
                "date": str(df.iloc[-1]["date"].date()),
                "price": df.iloc[-1]["close"],
                "pnl": round(pnl, 4),
                "note": "open position closed at period end",
            }
        )

    sell_trades = [t for t in trades if t["type"] == "sell"]
    if not sell_trades:
        return {
            "error": "No completed trades in this period — try a longer date range or different windows",
            "trades": trades,
        }

    pnls = [t["pnl"] for t in sell_trades]

    total_return = 1.0
    for p in pnls:
        total_return *= 1 + p
    total_return -= 1

    buy_hold = (df.iloc[-1]["close"] - df.iloc[0]["close"]) / df.iloc[0]["close"]
    win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

    equity = pd.Series([1.0])
    for p in pnls:
        equity = pd.concat(
            [equity, pd.Series([equity.iloc[-1] * (1 + p)])], ignore_index=True
        )
    rolling_max = equity.cummax()
    max_drawdown = ((equity - rolling_max) / rolling_max).min()

    if len(pnls) > 1:
        mean_r = sum(pnls) / len(pnls)
        std_r = (sum((p - mean_r) ** 2 for p in pnls) / (len(pnls) - 1)) ** 0.5
        sharpe = (mean_r / std_r) if std_r > 0 else None
    else:
        sharpe = None

    return {
        "total_return": round(total_return, 4),
        "buy_and_hold_return": round(buy_hold, 4),
        "outperformance": round(total_return - buy_hold, 4),
        "num_trades": len(sell_trades),
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(max_drawdown, 4),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "trades": trades,
    }
