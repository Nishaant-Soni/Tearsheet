import math

import numpy as np
import pandas as pd
import pytest

from tearsheet.analysis.backtest import (
    backtest_ma_crossover,
    crossover_signals,
    run_signals,
)


def bars(closes, opens=None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    opens = closes if opens is None else np.asarray(opens, dtype=float)
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", name="date")
    return pd.DataFrame(
        {"open": opens, "high": closes, "low": closes, "close": closes}, index=idx
    )


def signals(n, buy=None, sell=None) -> np.ndarray:
    s = np.zeros(n, dtype=int)
    if buy is not None:
        s[buy] = 1
    if sell is not None:
        s[sell] = -1
    return s


def test_intra_trade_drawdown_is_captured():
    # Enter at bar 2's open (100), fall 20% to 80, recover, exit at bar 7's open (105).
    closes = [100, 100, 100, 80, 90, 105, 105, 105, 105]
    bt = run_signals(bars(closes), signals(9, buy=1, sell=6), cost_bps=0)
    assert bt.trades[0].ret == pytest.approx(0.05)
    # Old code only looked at trade exits and reported 0 here.
    assert bt.max_drawdown <= -0.20 + 1e-12
    assert bt.max_drawdown_end == bt.equity.index[3]


def test_fill_is_next_open_not_signal_close():
    closes = [100, 101, 102, 103, 104, 105]
    opens = [99, 100.5, 101.7, 102.2, 103.9, 104.1]
    bt = run_signals(bars(closes, opens), signals(6, buy=1, sell=3), cost_bps=0)
    t = bt.trades[0]
    assert t.signal_date == bt.equity.index[1] and t.entry_date == bt.equity.index[2]
    assert t.entry_price == 101.7 and t.entry_price != closes[1]
    assert t.exit_price == 103.9
    assert t.ret == pytest.approx(103.9 / 101.7 - 1)


def test_cost_bps_changes_total_return_by_expected_amount():
    closes = [100, 100, 110, 120, 120, 120]
    free = run_signals(bars(closes), signals(6, buy=1, sell=3), cost_bps=0)
    paid = run_signals(bars(closes), signals(6, buy=1, sell=3), cost_bps=50)
    assert paid.total_return == pytest.approx((1 + free.total_return) * 0.995**2 - 1)
    assert paid.trades[0].ret == pytest.approx(paid.total_return)


def test_flat_series_sharpe_is_none():
    bt = backtest_ma_crossover(bars([50.0] * 40), 5, 10)
    assert bt.sharpe_ratio is None and bt.num_trades == 0
    assert any("No completed trades" in n for n in bt.notes)


def test_signal_on_last_bar_is_not_filled():
    bt = run_signals(bars([1, 2, 3, 4]), signals(4, buy=3), cost_bps=0)
    assert bt.trades == [] and bt.total_return == 0
    assert any("last bar" in n for n in bt.notes)


def test_open_position_marked_to_last_close_not_counted():
    bt = run_signals(bars([100, 100, 100, 110, 121]), signals(5, buy=1), cost_bps=0)
    assert bt.num_trades == 0 and bt.trades[0].open_at_end
    assert bt.trades[0].ret == pytest.approx(0.21)
    assert bt.total_return == pytest.approx(0.21)
    assert bt.exposure == pytest.approx(3 / 5)


def test_sharpe_and_volatility_formulas():
    rng = np.random.default_rng(1)
    closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 60))
    bt = run_signals(bars(closes), signals(60, buy=0), cost_bps=0, risk_free_rate=0.03)
    daily = bt.equity.pct_change().fillna(0).to_numpy()[1:]
    std = daily.std(ddof=1)
    assert bt.annualized_volatility == pytest.approx(std * math.sqrt(252))
    assert bt.sharpe_ratio == pytest.approx(
        (daily.mean() - 0.03 / 252) / std * math.sqrt(252)
    )


def test_crossover_end_to_end():
    closes = [10] * 6 + [9, 8, 7, 8, 10, 12, 14, 16, 15, 13, 11, 9, 8, 8]
    df = bars(closes)
    sig = crossover_signals(df["close"], 2, 4)["signal"]
    bt = backtest_ma_crossover(df, 2, 4, cost_bps=0)
    buys = list(df.index[sig == 1])
    assert bt.buy_signals == buys and bt.trades[0].signal_date == buys[0]
    entry_pos = df.index.get_loc(buys[0]) + 1
    assert bt.trades[0].entry_price == closes[entry_pos]
    assert bt.num_trades == 1


def test_needs_one_full_long_window_including_warmup():
    with pytest.raises(ValueError, match="at least 10"):
        backtest_ma_crossover(bars([1.0] * 9), 5, 10)
    # Exactly long_window bars is enough now that warm-up bars count.
    backtest_ma_crossover(bars([1.0] * 10), 5, 10)
    with pytest.raises(ValueError, match="greater"):
        backtest_ma_crossover(bars([1.0] * 50), 10, 10)
