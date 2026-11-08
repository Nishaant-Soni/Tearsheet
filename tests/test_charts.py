import numpy as np
import pandas as pd
import pytest
from matplotlib.ticker import PercentFormatter

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


MSFT_FCF = [
    ("2023-06-30", 59_475_000_000.0),
    ("2024-06-30", 74_071_000_000.0),
    ("2025-06-30", 71_611_000_000.0),
    ("2026-06-30", 66_987_000_000.0),
]


def bar_labels(fig) -> list[str]:
    return [t.get_text() for t in fig.axes[0].texts]


def y_tick(fig, value: float) -> str:
    return fig.axes[0].yaxis.get_major_formatter()(value, 0)


@pytest.mark.parametrize(
    "value, unit, currency, scale, expected",
    [
        (0.4879, "percent", "USD", (1.0, ""), "48.8%"),
        (0.4, "multiple", "USD", (1.0, ""), "0.40x"),
        (1.0232, "multiple", None, (1.0, ""), "1.02x"),
        (59_475_000_000.0, "amount", "USD", (1e9, "B"), "$59.5B"),
        (59_475_000_000.0, "amount", "TWD", (1e9, "B"), "59.5B TWD"),
        (59_475_000_000.0, "amount", None, (1e9, "B"), "59.5B"),
        (-147_782_000_000.0, "amount", "USD", (1e9, "B"), "-$147.8B"),
        (7.7134, "per_share", "USD", (1.0, ""), "$7.71"),
        (None, "amount", "USD", (1e9, "B"), "n/a"),
    ],
)
def test_format_metric(value, unit, currency, scale, expected):
    assert charts.format_metric(value, unit, currency, *scale) == expected


@pytest.mark.parametrize(
    "values, expected",
    [
        ([5.9e10, 7.4e10], (1e9, "B")),
        ([3.2e12, 1.0e9], (1e12, "T")),
        ([450e6], (1e6, "M")),
        ([-2.5e9, 1e8], (1e9, "B")),
        ([12.0], (1.0, "")),
        ([], (1.0, "")),
    ],
)
def test_amount_scale(values, expected):
    assert charts.amount_scale(values) == expected


def test_currency_amounts_read_in_billions_not_scientific():
    fig = charts.fundamental_figure(MSFT_FCF, "MSFT", "free_cash_flow", "amount", "USD")
    labels = bar_labels(fig)
    assert labels == ["$59.5B", "$74.1B", "$71.6B", "$67.0B"]
    assert y_tick(fig, 60e9) == "$60B" and y_tick(fig, 0) == "$0B"
    assert fig.axes[0].get_ylabel() == "free cash flow (USD, billions)"
    # No offset/multiplier text such as "1e10" above the axis.
    fig.canvas.draw()
    assert fig.axes[0].yaxis.get_offset_text().get_text() == ""
    assert not any("e+" in t for t in labels)


def test_non_usd_amounts_use_currency_code():
    fig = charts.fundamental_figure(
        [("2025-12-31", 1.6976e12)], "TSM", "ebitda", "amount", "TWD"
    )
    assert bar_labels(fig) == ["1.7T TWD"]
    assert fig.axes[0].get_ylabel() == "ebitda (TWD, trillions)"


def test_multiples_are_not_percentages():
    points = [("2024-09-30", 1.8723), ("2025-09-30", 1.338)]
    fig = charts.fundamental_figure(points, "AAPL", "debt_to_equity", "multiple", "USD")
    assert bar_labels(fig) == ["1.87x", "1.34x"]
    assert y_tick(fig, 0.5) == "0.5x"
    assert not any("%" in t for t in bar_labels(fig))


def test_percent_and_missing_values():
    points = [("2024-12-31", 0.4), ("2025-12-31", None)]
    fig = charts.fundamental_figure(points, "X", "net_margin", "percent", "USD")
    assert bar_labels(fig) == ["40.0%", "n/a"]
    # PercentFormatter picks decimals from the axis range, so only check the unit.
    assert isinstance(fig.axes[0].yaxis.get_major_formatter(), PercentFormatter)
    assert y_tick(fig, 0.25).startswith("25") and y_tick(fig, 0.25).endswith("%")


def test_per_share_and_negative_amounts():
    fig = charts.fundamental_figure(
        [("2025", 7.7134)], "AAPL", "book_value_per_share", "per_share", "USD"
    )
    assert bar_labels(fig) == ["$7.71"]
    assert fig.axes[0].get_ylabel() == "book value per share (USD per share)"
    fig = charts.fundamental_figure(
        [("2024", -42.0e9), ("2025", -147.8e9)],
        "JPM",
        "free_cash_flow",
        "amount",
        "USD",
    )
    assert bar_labels(fig) == ["-$42.0B", "-$147.8B"]
    assert all(t.get_va() == "top" for t in fig.axes[0].texts)


def test_fundamental_chart_returns_png():
    png = charts.fundamental_chart(MSFT_FCF, "MSFT", "free_cash_flow", "amount", "USD")
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
