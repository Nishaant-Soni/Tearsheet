import os
import platform
import subprocess
from io import BytesIO

import matplotlib

# mcp 2.x runs sync tools in worker threads; GUI backends crash off the main thread.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd
from mcp.server.mcpserver import Image

from tearsheet.analysis.backtest import calculate_trading_opportunities

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
os.makedirs(_DATA_DIR, exist_ok=True)


def _open_file(filepath: str) -> None:
    """Open a file with the system's default application."""
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", filepath])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", filepath])
    elif system == "Windows":
        os.startfile(filepath)


def _save_and_return(buf: BytesIO, filename: str) -> Image:
    img_bytes = buf.read()
    filepath = os.path.join(_DATA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(img_bytes)
    _open_file(filepath)
    return Image(data=img_bytes, format="png")


def plot_price_chart(
    prices: list,
    chart_type: str = "line",
    title: str = "Price Chart",
    filename: str | None = None,
) -> Image:
    from matplotlib.ticker import MaxNLocator

    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    if chart_type == "line":
        ax.plot(df["date"], df["close"], label="Close Price")
        ax.set_ylabel("Close Price")
    elif chart_type == "candlestick":
        try:
            from mplfinance.original_flavor import candlestick_ohlc
        except ImportError:
            raise ImportError("mplfinance is required for candlestick charts")
        df_ohlc = df[["date", "open", "high", "low", "close"]].copy()
        df_ohlc["date"] = mdates.date2num(df_ohlc["date"])
        candlestick_ohlc(ax, df_ohlc.values, width=0.6, colorup="g", colordown="r")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.set_ylabel("Price")
    else:
        raise ValueError(f"Unknown chart_type: {chart_type}")
    ax.set_title(title)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True)
    fig.autofmt_xdate()
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _save_and_return(buf, filename or f"price_chart_{chart_type}.png")


def plot_financial_metric(
    dates: list,
    values: list,
    metric_name: str = "Metric",
    title: str = "Financial Metric",
    filename: str | None = None,
) -> Image:
    fig, ax = plt.subplots(figsize=(10, 5))
    parsed_dates = pd.to_datetime(dates)
    ax.plot(parsed_dates, values, marker="o", label=metric_name)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel(metric_name)
    ax.legend()
    ax.grid(True)
    fig.autofmt_xdate()
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _save_and_return(buf, filename or f"financial_metric_{metric_name}.png")


def plot_comparison_chart(
    dates: list,
    series: dict,
    title: str = "Comparison Chart",
    filename: str | None = None,
    normalized: bool = False,
) -> Image:
    fig, ax = plt.subplots(figsize=(10, 5))
    parsed_dates = pd.to_datetime(dates)
    for label, values in series.items():
        if normalized:
            first = next((v for v in values if v is not None and v != 0), None)
            plot_values = [
                v / first * 100 if v is not None and first else float("nan")
                for v in values
            ]
        else:
            plot_values = values
        ax.plot(parsed_dates, plot_values, marker="o", label=label)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Indexed Value (base = 100)" if normalized else "Value")
    ax.legend()
    ax.grid(True)
    fig.autofmt_xdate()
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _save_and_return(buf, filename or "comparison_chart.png")


def plot_trading_opportunities(
    prices: list,
    short_window: int = 9,
    long_window: int = 21,
    title: str = "Trading Opportunities",
) -> Image:
    prices_df = pd.DataFrame(prices)
    prices_df["date"] = pd.to_datetime(prices_df["date"])
    prices_df = calculate_trading_opportunities(prices_df, short_window, long_window)
    buy_signals = prices_df[prices_df["signal"] == 1]
    sell_signals = prices_df[prices_df["signal"] == -1]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        prices_df["date"],
        prices_df["close"],
        label="Close Price",
        color="blue",
        alpha=0.5,
    )
    ax.plot(
        prices_df["date"],
        prices_df["short_ma"],
        label=f"Short MA ({short_window})",
        color="orange",
    )
    ax.plot(
        prices_df["date"],
        prices_df["long_ma"],
        label=f"Long MA ({long_window})",
        color="magenta",
    )
    if not buy_signals.empty:
        plt.scatter(
            buy_signals["date"],
            buy_signals["close"],
            marker="^",
            color="green",
            label="Buy Signal",
            s=100,
            zorder=5,
        )
    if not sell_signals.empty:
        plt.scatter(
            sell_signals["date"],
            sell_signals["close"],
            marker="v",
            color="red",
            label="Sell Signal",
            s=100,
            zorder=5,
        )
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True)
    fig.autofmt_xdate()
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _save_and_return(buf, "trading_opportunities.png")
