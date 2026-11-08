"""Shared fixtures. No test may reach the network: yfinance is replaced by fakes."""

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from tearsheet.data import market

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


@dataclass
class FakeSymbol:
    history: pd.DataFrame | None = None
    fast_info: dict | None = None
    info: dict | None = None
    dividends: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    splits: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


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
        self._yahoo.history_calls.append({"ticker": self.ticker, **kwargs})
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


@pytest.fixture(autouse=True)
def fake_yahoo(monkeypatch) -> Iterator[FakeYahoo]:
    """Replace yfinance for every test and start each test with empty caches."""
    yahoo = FakeYahoo()
    monkeypatch.setattr("yfinance.Ticker", yahoo.ticker)
    monkeypatch.setattr("yfinance.Search", yahoo.search)
    market.clear_caches()
    yield yahoo
    market.clear_caches()


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
