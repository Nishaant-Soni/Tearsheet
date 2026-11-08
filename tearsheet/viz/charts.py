"""Chart rendering as pure functions: DataFrames in, PNG bytes out.

Uses matplotlib's object API (Figure + Agg canvas) and never pyplot's global state,
because tools render in worker threads. Nothing here touches the filesystem or
the network; see viz/storage.py for saving.
"""

from io import BytesIO

import matplotlib

matplotlib.use("Agg")  # mplfinance imports pyplot; keep it off GUI backends

import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from tearsheet.analysis.backtest import crossover_signals  # noqa: E402

FIGSIZE = (10, 5)
DPI = 100


def _new_figure() -> Figure:
    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    FigureCanvasAgg(fig)
    return fig


def _to_png(fig: Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    return buf.getvalue()


def price_chart(
    df: pd.DataFrame, ticker: str, chart_type: str, title: str | None
) -> bytes:
    """Line chart of closes, or OHLC candlesticks with a volume panel."""
    fig = _new_figure()
    title = (
        title or f"{ticker} {'candlestick' if chart_type == 'candlestick' else 'close'}"
    )
    if chart_type == "candlestick":
        ax = fig.add_axes((0.08, 0.30, 0.88, 0.62))
        vax = fig.add_axes((0.08, 0.08, 0.88, 0.18), sharex=ax)
        ohlc = df.rename(columns=str.capitalize)[
            ["Open", "High", "Low", "Close", "Volume"]
        ]
        mpf.plot(ohlc, type="candle", style="yahoo", ax=ax, volume=vax)
        ax.set_ylabel("Price")
        ax.tick_params(labelbottom=False)
    else:
        ax = fig.add_subplot()
        ax.plot(df.index, df["close"], label="Close")
        ax.set_ylabel("Close")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
    ax.set_title(title)
    return _to_png(fig)


def normalize_to_100(closes: pd.DataFrame) -> pd.DataFrame:
    """Rebase each column to 100 at its first non-null value."""
    return closes.apply(
        lambda s: s / s.dropna().iloc[0] * 100 if s.notna().any() else s
    )


def comparison_chart(
    closes: pd.DataFrame, normalized: bool, title: str | None
) -> bytes:
    """One line per column (ticker), aligned on dates."""
    data = normalize_to_100(closes) if normalized else closes
    fig = _new_figure()
    ax = fig.add_subplot()
    for col in data.columns:
        series = data[col].dropna()
        ax.plot(series.index, series.to_numpy(), label=col)
    ax.set_title(title or " vs ".join(data.columns))
    ax.set_ylabel("Indexed value (base = 100)" if normalized else "Close")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _to_png(fig)


def fundamental_chart(
    points: list[tuple[str, float | None]], ticker: str, metric: str, is_ratio: bool
) -> bytes:
    """Bar chart of one metric per fiscal period, oldest first."""
    labels = [end for end, _ in points]
    values = [v if v is not None else 0.0 for _, v in points]
    fig = _new_figure()
    ax = fig.add_subplot()
    positions = list(range(len(labels)))
    bars = ax.bar(
        positions,
        values,
        color=["#4C72B0" if v is not None else "#CCCCCC" for _, v in points],
    )
    for bar, (_, v) in zip(bars, points):
        text = "n/a" if v is None else (f"{v:.1%}" if is_ratio else f"{v:,.3g}")
        ax.annotate(
            text,
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            ha="center",
            va="bottom",
        )
    ax.set_xticks(positions, labels)
    ax.set_title(f"{ticker} {metric.replace('_', ' ')}")
    ax.set_xlabel("Period end")
    ax.grid(True, axis="y", alpha=0.3)
    if is_ratio:
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    return _to_png(fig)


def ma_crossover_chart(
    df: pd.DataFrame,
    ticker: str,
    short_window: int,
    long_window: int,
    title: str | None,
) -> bytes:
    """Close with both SMAs and markers at the buy/sell signal closes."""
    sig = crossover_signals(df["close"], short_window, long_window)
    buys = sig["signal"] == 1
    sells = sig["signal"] == -1
    fig = _new_figure()
    ax = fig.add_subplot()
    ax.plot(df.index, df["close"], label="Close", color="tab:blue", alpha=0.5)
    ax.plot(df.index, sig["short_ma"], label=f"SMA {short_window}", color="tab:orange")
    ax.plot(df.index, sig["long_ma"], label=f"SMA {long_window}", color="tab:purple")
    ax.scatter(
        df.index[buys],
        df["close"][buys],
        marker="^",
        color="green",
        s=100,
        zorder=5,
        label="Buy signal",
    )
    ax.scatter(
        df.index[sells],
        df["close"][sells],
        marker="v",
        color="red",
        s=100,
        zorder=5,
        label="Sell signal",
    )
    ax.set_title(title or f"{ticker} SMA {short_window}/{long_window} crossover")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _to_png(fig)
