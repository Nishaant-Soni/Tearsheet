import numpy as np
import pandas as pd
import pytest

from tearsheet.data.market import normalize_history
from tearsheet.viz import charts
from tests.conftest import make_ohlcv

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def df():
    return normalize_history(make_ohlcv(100 + 10 * np.sin(np.arange(120) / 8)))


def test_price_charts_return_png(df):
    for kind in ("line", "candlestick"):
        png = charts.price_chart(df, "AAPL", kind, None)
        assert png.startswith(PNG) and len(png) > 5000


def test_comparison_chart_returns_png(df):
    closes = pd.DataFrame({"A": df["close"], "B": df["close"] * 3})
    assert charts.comparison_chart(closes, True, "t").startswith(PNG)
    assert charts.comparison_chart(closes, False, None).startswith(PNG)


def test_normalize_uses_first_non_null_close():
    closes = pd.DataFrame({"A": [np.nan, 50.0, 75.0], "B": [10.0, 20.0, 5.0]})
    out = charts.normalize_to_100(closes)
    assert out["A"].tolist()[1:] == [100.0, 150.0] and np.isnan(out["A"].iloc[0])
    assert out["B"].tolist() == [100.0, 200.0, 50.0]


def test_fundamental_chart_handles_missing_values():
    png = charts.fundamental_chart(
        [("2024-12-31", 0.4), ("2025-12-31", None)], "X", "net_margin", True
    )
    assert png.startswith(PNG)


def test_crossover_chart_returns_png(df):
    assert charts.ma_crossover_chart(df, "AAPL", 5, 20, None).startswith(PNG)


def test_charts_never_use_pyplot_figures(df, monkeypatch):
    import matplotlib.pyplot as plt

    for name in ("figure", "subplots", "scatter", "plot", "savefig", "gcf", "gca"):
        monkeypatch.setattr(
            plt, name, lambda *a, _n=name, **k: pytest.fail(f"pyplot.{_n} used")
        )
    charts.price_chart(df, "AAPL", "line", None)
    charts.price_chart(df, "AAPL", "candlestick", None)
    charts.ma_crossover_chart(df, "AAPL", 5, 20, None)
