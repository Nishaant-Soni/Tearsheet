"""Shared fixtures. No test may reach the network: yfinance is replaced by fakes."""

import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from tearsheet.data import fundamentals, market

EXCHANGE_TZ = "America/New_York"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_ohlcv(
    closes, start: str = "2024-01-02", freq: str = "B", tz: str = EXCHANGE_TZ
) -> pd.DataFrame:
    """A yfinance-style frame: capitalized columns, tz-aware index."""
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz=tz, name="Date")
    return pd.DataFrame(
        {
            "Open": closes * 0.99,
            "High": closes * 1.01,
            "Low": closes * 0.98,
            "Close": closes,
            "Volume": np.full(len(closes), 1_000_000),
        },
        index=idx,
    )


def make_actions(pairs, tz: str = EXCHANGE_TZ) -> pd.Series:
    """Dividend/split series stamped at 09:30 local time, like yfinance 1.x."""
    idx = pd.DatetimeIndex([pd.Timestamp(d + " 09:30") for d, _ in pairs]).tz_localize(
        tz
    )
    return pd.Series([v for _, v in pairs], index=idx, dtype=float)


def make_statement(rows: dict[str, list], period_ends: list[str]) -> pd.DataFrame:
    """A yfinance-style statement: row labels x Timestamp period-end columns."""
    cols = [pd.Timestamp(d) for d in period_ends]
    return pd.DataFrame(
        {c: [vals[i] for vals in rows.values()] for i, c in enumerate(cols)},
        index=list(rows),
        dtype=float,
    )


STATEMENT_ATTRS = {
    "financials",
    "balance_sheet",
    "cashflow",
    "quarterly_financials",
    "quarterly_balance_sheet",
    "quarterly_cashflow",
}


@dataclass
class FakeSymbol:
    history: pd.DataFrame | None = None
    fast_info: dict | None = None
    info: dict | None = None
    dividends: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    splits: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    statements: dict[str, pd.DataFrame] = field(default_factory=dict)


class FakeYahoo:
    """Registry of fake symbols plus call log, installed in place of yfinance."""

    def __init__(self) -> None:
        self.symbols: dict[str, FakeSymbol] = {}
        self.history_calls: list[dict] = []
        self.info_calls: list[str] = []
        self.search_results: list[dict] = []

    def add(self, symbol: str, **kwargs) -> FakeSymbol:
        self.symbols[symbol] = FakeSymbol(**kwargs)
        return self.symbols[symbol]

    def ticker(self, symbol: str) -> "FakeTicker":
        return FakeTicker(self, symbol)

    def search(self, query: str, **kwargs):
        return type("Search", (), {"quotes": self.search_results})()


class FakeTicker:
    def __init__(self, yahoo: FakeYahoo, symbol: str) -> None:
        self._yahoo = yahoo
        self._sym = yahoo.symbols.get(symbol)
        self.ticker = symbol

    def history(self, **kwargs) -> pd.DataFrame:
        self._yahoo.history_calls.append(
            {"ticker": self.ticker, "thread": threading.current_thread().name, **kwargs}
        )
        if self._sym is None or self._sym.history is None:
            return pd.DataFrame()
        df = self._sym.history
        start = pd.Timestamp(kwargs["start"]).tz_localize(df.index.tz)
        end = pd.Timestamp(kwargs["end"]).tz_localize(df.index.tz)
        return df[(df.index >= start) & (df.index < end)].copy()

    @property
    def fast_info(self) -> dict:
        if self._sym is None or self._sym.fast_info is None:
            return {}  # missing keys raise KeyError, like yfinance for bad symbols
        return self._sym.fast_info

    @property
    def info(self) -> dict:
        self._yahoo.info_calls.append(self.ticker)
        if self._sym is None or self._sym.info is None:
            return {"trailingPegRatio": None}
        return self._sym.info

    @property
    def dividends(self) -> pd.Series:
        return pd.Series(dtype=float) if self._sym is None else self._sym.dividends

    @property
    def splits(self) -> pd.Series:
        return pd.Series(dtype=float) if self._sym is None else self._sym.splits

    def __getattr__(self, name: str):
        if name in STATEMENT_ATTRS:
            if self._sym is None:
                return pd.DataFrame()
            return self._sym.statements.get(name, pd.DataFrame())
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Fail any outbound connection outside tests marked `live`."""
    if request.node.get_closest_marker("live") is None:

        def refuse(*args, **kwargs):
            raise RuntimeError("network access in an offline test")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket.socket, "connect_ex", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def chart_dir(monkeypatch, tmp_path):
    """Charts go to a temp dir, and the image viewer stays off, in every test."""
    path = tmp_path / "charts"
    monkeypatch.setenv("TEARSHEET_DATA_DIR", str(path))
    monkeypatch.delenv("TEARSHEET_OPEN_CHARTS", raising=False)
    return path


@pytest.fixture(autouse=True)
def fake_yahoo(monkeypatch, request) -> Iterator[FakeYahoo]:
    """Replace yfinance for every test and start each test with empty caches.

    Tests marked `live` keep the real yfinance (run them with `pytest -m live`).
    """
    yahoo = FakeYahoo()
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr("yfinance.Ticker", yahoo.ticker)
        monkeypatch.setattr("yfinance.Search", yahoo.search)
    market.clear_caches()
    fundamentals.clear_caches()
    yield yahoo
    market.clear_caches()
    fundamentals.clear_caches()


@pytest.fixture
def aapl(fake_yahoo: FakeYahoo) -> FakeSymbol:
    closes = np.linspace(100, 120, 60)
    return fake_yahoo.add(
        "AAPL",
        history=make_ohlcv(closes),
        fast_info={
            "lastPrice": 120.0,
            "previousClose": 118.0,
            "currency": "USD",
            "marketCap": 1.9e12,
            "shares": 1.6e10,
            "exchange": "NMS",
        },
        info={"longName": "Apple Inc.", "quoteType": "EQUITY", "sector": "Technology"},
        dividends=make_actions([("2023-11-10", 0.24), ("2024-02-09", 0.24)]),
        splits=make_actions([("2014-06-09", 7.0), ("2020-08-31", 4.0)]),
    )


ANNUAL_ENDS = ["2025-06-30", "2024-06-30"]
QUARTER_ENDS = ["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]


@pytest.fixture
def acme(fake_yahoo: FakeYahoo) -> FakeSymbol:
    """A company with annual and quarterly statements using yfinance labels."""
    income = {
        "Total Revenue": [1000.0, 800.0],
        "Cost Of Revenue": [400.0, 360.0],
        "Gross Profit": [600.0, 440.0],
        "Operating Income": [300.0, 200.0],
        "Net Income": [200.0, 120.0],
        "EBITDA": [350.0, 240.0],
        "Diluted EPS": [2.0, 1.2],
        "Diluted Average Shares": [100.0, 100.0],
        "Tax Rate For Calcs": [0.21, 0.21],  # not mapped
    }
    balance = {
        "Total Assets": [5000.0, 4000.0],
        "Total Liabilities Net Minority Interest": [3000.0, 2500.0],
        "Stockholders Equity": [2000.0, 1500.0],
        "Current Assets": [1500.0, 1200.0],
        "Current Liabilities": [1000.0, 1000.0],
        "Inventory": [300.0, 200.0],
        "Total Debt": [800.0, 900.0],
        "Cash And Cash Equivalents": [400.0, 300.0],
        "Ordinary Shares Number": [100.0, 100.0],
        "Goodwill": [50.0, 50.0],  # not mapped
    }
    cash = {
        "Operating Cash Flow": [500.0, 350.0],
        "Capital Expenditure": [-100.0, -50.0],
        "Free Cash Flow": [400.0, 300.0],
        "Cash Dividends Paid": [-80.0, -70.0],
        "Depreciation And Amortization": [50.0, 40.0],
    }
    q_income = {
        "Total Revenue": [260.0, 250.0, 250.0, 240.0],
        "Net Income": [52.0, 50.0, 50.0, 48.0],
        "Diluted EPS": [0.5, 0.5, 0.5, 0.5],
    }
    q_balance = {
        "Total Assets": [5000.0, 4900.0, 4800.0, 4700.0],
        "Stockholders Equity": [2000.0, 1900.0, 1800.0, 1700.0],
        "Total Debt": [800.0, 820.0, 840.0, 860.0],
    }
    return fake_yahoo.add(
        "ACME",
        fast_info={"lastPrice": 40.0, "previousClose": 39.0, "currency": "USD"},
        info={
            "longName": "Acme Corp",
            "quoteType": "EQUITY",
            "financialCurrency": "USD",
        },
        statements={
            "financials": make_statement(income, ANNUAL_ENDS),
            "balance_sheet": make_statement(balance, ANNUAL_ENDS),
            "cashflow": make_statement(cash, ANNUAL_ENDS),
            "quarterly_financials": make_statement(q_income, QUARTER_ENDS),
            "quarterly_balance_sheet": make_statement(q_balance, QUARTER_ENDS),
        },
    )
