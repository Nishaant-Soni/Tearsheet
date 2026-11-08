import pandas as pd


def calculate_technical_indicators(
    price_data: list, indicator: str, window: int = 14
) -> dict:
    """
    Calculates technical indicators on stock price data.
    Args:
        price_data: List of closing prices (numbers) OR list of OHLCV dicts with keys
                    'open', 'high', 'low', 'close'. OHLCV form is required for 'atr'
                    and 'stochastic'; either form works for all others.
        indicator: 'sma', 'ema', 'rsi', 'macd', 'volatility', 'bollinger_bands', 'atr', 'stochastic'
        window: Window size for the indicator.
    Returns:
        Dict with indicator values.
    """
    result = {}
    if price_data and isinstance(price_data[0], dict):
        closes = pd.Series([d["close"] for d in price_data])
        highs = pd.Series([d.get("high", d["close"]) for d in price_data])
        lows = pd.Series([d.get("low", d["close"]) for d in price_data])
    else:
        closes = pd.Series(price_data)
        highs = closes
        lows = closes
    try:
        if indicator == "sma":
            result["sma"] = closes.rolling(window=window).mean().tolist()
        elif indicator == "ema":
            result["ema"] = closes.ewm(span=window, adjust=False).mean().tolist()
        elif indicator == "rsi":
            delta = closes.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            alpha = 1.0 / window
            avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
            avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            result["rsi"] = rsi.tolist()
        elif indicator == "macd":
            ema12 = closes.ewm(span=12, adjust=False).mean()
            ema26 = closes.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            result["macd"] = macd.tolist()
            result["macd_signal"] = signal.tolist()
        elif indicator == "volatility":
            result["volatility"] = (
                closes.pct_change().rolling(window=window).std().tolist()
            )
        elif indicator == "bollinger_bands":
            middle = closes.rolling(window=window).mean()
            std = closes.rolling(window=window).std()
            result["upper"] = (middle + 2 * std).tolist()
            result["middle"] = middle.tolist()
            result["lower"] = (middle - 2 * std).tolist()
        elif indicator == "atr":
            prev_close = closes.shift(1)
            tr = pd.concat(
                [
                    highs - lows,
                    (highs - prev_close).abs(),
                    (lows - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            result["atr"] = tr.ewm(alpha=1.0 / window, adjust=False).mean().tolist()
        elif indicator == "stochastic":
            lowest_low = lows.rolling(window=window).min()
            highest_high = highs.rolling(window=window).max()
            denom = highest_high - lowest_low
            k = 100 * (closes - lowest_low) / denom.replace(0, float("nan"))
            d = k.rolling(window=3).mean()
            result["stochastic_k"] = k.tolist()
            result["stochastic_d"] = d.tolist()
        else:
            result["error"] = f"Unknown indicator: {indicator}"
    except Exception as e:
        result["error"] = str(e)
    return result
