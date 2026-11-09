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
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

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


SCALES = ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K"))
SCALE_WORDS = {
    "T": "trillions",
    "B": "billions",
    "M": "millions",
    "K": "thousands",
    "": "",
}


def amount_scale(values: list[float]) -> tuple[float, str]:
    """Divisor and suffix (T, B, M, K or none) that suit the largest magnitude."""
    biggest = max((abs(v) for v in values), default=0.0)
    for divisor, suffix in SCALES:
        if biggest >= divisor:
            return divisor, suffix
    return 1.0, ""


def _trim(x: float, decimals: int) -> str:
    text = f"{x:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_money(
    value: float,
    currency: str | None,
    divisor: float = 1.0,
    suffix: str = "",
    decimals: int = 1,
    trim: bool = False,
) -> str:
    """$59.5B for USD, 59.5B TWD for other currencies, 59.5B when unknown.

    trim drops trailing zeros (axis ticks: $60B rather than $60.0B).
    """
    sign = "-" if value < 0 else ""
    scaled = abs(value) / divisor
    number = _trim(scaled, decimals) if trim else f"{scaled:,.{decimals}f}"
    amount = f"{number}{suffix}"
    if currency == "USD":
        return f"{sign}${amount}"
    return f"{sign}{amount} {currency}" if currency else f"{sign}{amount}"


def format_metric(
    value: float | None,
    unit: str,
    currency: str | None,
    divisor: float = 1.0,
    suffix: str = "",
) -> str:
    if value is None:
        return "n/a"
    if unit == "percent":
        return f"{value:.1%}"
    if unit == "multiple":
        return f"{value:.2f}x"
    if unit == "per_share":
        return format_money(value, currency, decimals=2)
    return format_money(value, currency, divisor, suffix)


def fundamental_figure(
    points: list[tuple[str, float | None]],
    ticker: str,
    metric: str,
    unit: str,
    currency: str | None = None,
) -> Figure:
    """Bar chart of one metric per fiscal period, oldest first.

    unit is percent, multiple, amount or per_share (see analysis.ratios.METRIC_UNITS).
    Amounts are scaled to T/B/M/K on both the bar labels and the y axis.
    """
    labels = [end for end, _ in points]
    values = [v if v is not None else 0.0 for _, v in points]
    divisor, suffix = (
        amount_scale([v for _, v in points if v is not None])
        if unit == "amount"
        else (1.0, "")
    )
    fig = _new_figure()
    ax = fig.add_subplot()
    positions = list(range(len(labels)))
    bars = ax.bar(
        positions,
        values,
        color=["#4C72B0" if v is not None else "#CCCCCC" for _, v in points],
    )
    for bar, (_, v) in zip(bars, points):
        negative = v is not None and v < 0
        ax.annotate(
            format_metric(v, unit, currency, divisor, suffix),
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            ha="center",
            va="top" if negative else "bottom",
        )
    if any(v < 0 for v in values):
        ax.axhline(0, color="black", linewidth=0.8)

    if unit == "percent":
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    elif unit == "multiple":
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{_trim(y, 2)}x"))
    else:
        decimals = 2 if unit == "per_share" else 1
        ax.yaxis.set_major_formatter(
            FuncFormatter(
                lambda y, _: format_money(
                    y, currency, divisor, suffix, decimals, trim=True
                )
            )
        )
    name = metric.replace("_", " ")
    if unit == "amount":
        scale = SCALE_WORDS[suffix]
        ax.set_ylabel(
            f"{name} ({currency or 'reporting currency'}{', ' + scale if scale else ''})"
        )
    elif unit == "per_share":
        ax.set_ylabel(f"{name} ({currency or 'reporting currency'} per share)")
    else:
        ax.set_ylabel(name)
    ax.set_xticks(positions, labels)
    ax.set_title(f"{ticker} {name}")
    ax.set_xlabel("Period end")
    ax.grid(True, axis="y", alpha=0.3)
    return fig


def fundamental_chart(
    points: list[tuple[str, float | None]],
    ticker: str,
    metric: str,
    unit: str,
    currency: str | None = None,
) -> bytes:
    return _to_png(fundamental_figure(points, ticker, metric, unit, currency))


def ma_crossover_chart(
    df: pd.DataFrame,
    ticker: str,
    short_window: int,
    long_window: int,
    title: str | None,
    first_in_range: int = 0,
    buy_dates: list[pd.Timestamp] | None = None,
    sell_dates: list[pd.Timestamp] | None = None,
) -> bytes:
    """Close with both SMAs and markers at the buy/sell signal closes.

    `df` may start with warm-up bars; SMAs use them but only bars from
    `first_in_range` on are drawn. Pass the backtest's signal dates so the chart
    and backtest agree; signals before the range are not drawn.
    """
    sig = crossover_signals(df["close"], short_window, long_window)
    if buy_dates is None:
        buy_dates = list(df.index[sig["signal"] == 1])
    if sell_dates is None:
        sell_dates = list(df.index[sig["signal"] == -1])
    view = df.iloc[first_in_range:]
    sig = sig.iloc[first_in_range:]
    buys = view.index.isin(buy_dates)
    sells = view.index.isin(sell_dates)
    fig = _new_figure()
    ax = fig.add_subplot()
    ax.plot(view.index, view["close"], label="Close", color="tab:blue", alpha=0.5)
    ax.plot(
        view.index, sig["short_ma"], label=f"SMA {short_window}", color="tab:orange"
    )
    ax.plot(view.index, sig["long_ma"], label=f"SMA {long_window}", color="tab:purple")
    ax.scatter(
        view.index[buys],
        view["close"][buys],
        marker="^",
        color="green",
        s=100,
        zorder=5,
        label="Buy signal",
    )
    ax.scatter(
        view.index[sells],
        view["close"][sells],
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
