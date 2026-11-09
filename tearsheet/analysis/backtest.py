"""Moving-average crossover backtest on daily OHLC bars.

Assumptions:
- Signals use simple moving averages of the close. A buy signal fires at the close
  of bar t when the short MA closes above the long MA after being at or below it
  on bar t-1; a sell signal is the reverse.
- Moving averages are computed over warm-up bars before the range plus the range,
  so they are defined from the first in-range bar. Trading and every metric start
  at the first in-range bar (`first_in_range`).
- Orders fill at the open of bar t+1, never at the signal bar's close. A signal on
  the last bar is not filled. A signal on the last warm-up bar fills at the first
  in-range open, and that trade keeps its true (pre-range) signal date.
- entry_mode="crossover" enters only on a fresh buy signal; "state" is long
  whenever the short MA is above the long MA at the close.
- Long-only: fully invested or flat. No leverage, shorting or position sizing.
- `cost_bps` is charged on every entry and exit (5 bps = 0.05% of the trade).
  There is no other slippage model.
- Returns are marked to market daily at the close. An open position at the end is
  valued at the last close and is not counted as a completed trade.
- Buy-and-hold runs from the open of the first in-range bar (the earliest fill the
  strategy could get) to the last close, without costs.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252
ENTRY_MODES = ("crossover", "state")


@dataclass
class Trade:
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_price: float
    exit_signal_date: pd.Timestamp | None = None
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    ret: float | None = None
    open_at_end: bool = False


@dataclass
class BacktestStats:
    total_return: float
    buy_and_hold_return: float
    excess_return: float
    cagr: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    max_drawdown: float
    max_drawdown_start: pd.Timestamp | None
    max_drawdown_end: pd.Timestamp | None
    num_trades: int
    win_rate: float | None
    avg_trade_return: float | None
    exposure: float
    trades: list[Trade]
    buy_signals: list[pd.Timestamp]
    sell_signals: list[pd.Timestamp]
    equity: pd.Series
    notes: list[str] = field(default_factory=list)


def crossover_signals(close: pd.Series, short: int, long: int) -> pd.DataFrame:
    """short_ma, long_ma and signal (+1 buy, -1 sell, 0 none) per bar."""
    s = close.rolling(short).mean()
    lg = close.rolling(long).mean()
    prev_s, prev_l = s.shift(1), lg.shift(1)
    signal = pd.Series(0, index=close.index)
    signal[(s > lg) & (prev_s <= prev_l)] = 1
    signal[(s < lg) & (prev_s >= prev_l)] = -1
    return pd.DataFrame({"short_ma": s, "long_ma": lg, "signal": signal})


def backtest_ma_crossover(
    df: pd.DataFrame,
    short_window: int,
    long_window: int,
    cost_bps: float = 5.0,
    risk_free_rate: float = 0.0,
    first_in_range: int = 0,
    entry_mode: str = "crossover",
) -> BacktestStats:
    """Backtest on `df` (warm-up bars, then the range starting at `first_in_range`)."""
    if short_window >= long_window:
        raise ValueError("long_window must be greater than short_window")
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"entry_mode must be one of {ENTRY_MODES}")
    if len(df) < long_window:
        raise ValueError(f"need at least {long_window} bars, got {len(df)}")
    if not 0 <= first_in_range < len(df):
        raise ValueError("first_in_range must point at a bar in df")
    sig = crossover_signals(df["close"], short_window, long_window)
    signals = sig["signal"].to_numpy()
    if entry_mode == "crossover":
        enter, exit_ = signals == 1, signals == -1
    else:
        above = (sig["short_ma"] > sig["long_ma"]).to_numpy()  # NaN compares False
        enter, exit_ = above, ~above
    return _simulate(
        df, enter, exit_, signals, cost_bps, risk_free_rate, first_in_range
    )


def run_signals(
    df: pd.DataFrame,
    signals: np.ndarray,
    cost_bps: float = 5.0,
    risk_free_rate: float = 0.0,
    first_in_range: int = 0,
) -> BacktestStats:
    """Simulate a long-only book from per-bar signals (+1 buy, -1 sell, 0 none)."""
    signals = np.asarray(signals)
    return _simulate(
        df,
        signals == 1,
        signals == -1,
        signals,
        cost_bps,
        risk_free_rate,
        first_in_range,
    )


def _simulate(
    df: pd.DataFrame,
    enter: np.ndarray,
    exit_: np.ndarray,
    signals: np.ndarray,
    cost_bps: float,
    risk_free_rate: float,
    first: int,
) -> BacktestStats:
    """Act on bar t's flags at bar t+1's open, from the first in-range bar onward."""
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    dates = df.index
    keep = 1.0 - cost_bps / 10_000  # fraction of capital kept after one fill

    n = len(df)
    daily = np.zeros(n)
    in_market = np.zeros(n, dtype=bool)  # holding at the close of bar i
    trades: list[Trade] = []
    position = False
    # With warm-up, the first in-range bar can act on the last warm-up bar's flags.
    for i in range(max(first, 1), n):
        if not position and enter[i - 1]:
            position = True
            trades.append(Trade(dates[i - 1], dates[i], opens[i]))
            daily[i] = keep * closes[i] / opens[i] - 1
        elif position and exit_[i - 1]:
            position = False
            t = trades[-1]
            t.exit_signal_date, t.exit_date, t.exit_price = (
                dates[i - 1],
                dates[i],
                opens[i],
            )
            t.ret = keep * keep * opens[i] / t.entry_price - 1
            daily[i] = keep * opens[i] / closes[i - 1] - 1
        elif position:
            daily[i] = closes[i] / closes[i - 1] - 1
        in_market[i] = position

    notes: list[str] = []
    start = dates[first]
    early = [t for t in trades if t.signal_date < start]
    if early:
        notes.append(
            f"The first trade's signal fired on {early[0].signal_date.date()}, the last "
            f"warm-up bar before the range, and filled at the first in-range open."
        )
    if position:
        t = trades[-1]
        t.exit_date, t.exit_price, t.open_at_end = dates[-1], closes[-1], True
        t.ret = keep * closes[-1] / t.entry_price - 1
        notes.append(
            "Position still open at the end: marked to the last close, no exit cost, "
            "not counted in num_trades."
        )
    if (not position and enter[-1]) or (position and exit_[-1]):
        notes.append(
            "A signal on the last bar was not filled (fills happen next open)."
        )

    equity = pd.Series(np.cumprod(1 + daily[first:]), index=dates[first:])
    total_return = equity.iloc[-1] - 1
    buy_and_hold = closes[-1] / opens[first] - 1

    years = (dates[-1] - start).days / 365.25
    cagr = (
        (equity.iloc[-1] ** (1 / years) - 1)
        if years > 0 and equity.iloc[-1] > 0
        else None
    )

    # Without warm-up, bar 0 can never hold a fill, so it carries no return.
    rets = daily[first:] if first > 0 else daily[1:]
    std = rets.std(ddof=1) if len(rets) > 1 else 0.0
    if std > 0 and math.isfinite(std):
        vol = std * math.sqrt(TRADING_DAYS)
        sharpe = (
            (rets.mean() - risk_free_rate / TRADING_DAYS)
            / std
            * math.sqrt(TRADING_DAYS)
        )
    else:
        vol, sharpe = (0.0 if std == 0 else None), None

    # Peak starts at the initial capital (1.0) so a loss on the entry day counts.
    peak = pd.Series(
        np.maximum.accumulate(np.r_[1.0, equity.to_numpy()])[1:], index=equity.index
    )
    drawdown = equity / peak - 1
    max_dd = float(min(drawdown.min(), 0.0))
    dd_start = dd_end = None
    if max_dd < 0:
        dd_end = drawdown.idxmin()
        before = equity.loc[:dd_end]
        dd_start = before.idxmax() if before.max() >= 1.0 else start

    closed = [t for t in trades if not t.open_at_end]
    if not closed:
        notes.append(
            "No completed trades in this range; try a longer range or shorter windows."
        )
    returns = [t.ret for t in closed if t.ret is not None]
    in_range_buys = [d for d, s in zip(dates[first:], signals[first:]) if s == 1]
    return BacktestStats(
        total_return=total_return,
        buy_and_hold_return=buy_and_hold,
        excess_return=total_return - buy_and_hold,
        cagr=cagr,
        annualized_volatility=vol,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        max_drawdown_start=dd_start,
        max_drawdown_end=dd_end,
        num_trades=len(closed),
        win_rate=sum(r > 0 for r in returns) / len(returns) if returns else None,
        avg_trade_return=sum(returns) / len(returns) if returns else None,
        exposure=float(in_market[first:].mean()),
        trades=trades,
        buy_signals=sorted({*(t.signal_date for t in early), *in_range_buys}),
        sell_signals=[d for d, s in zip(dates[first:], signals[first:]) if s == -1],
        equity=equity,
        notes=notes,
    )
