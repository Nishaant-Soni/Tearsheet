"""Pydantic input/output models and Literal types for tool parameters."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from tearsheet.errors import invalid_input

# ------------------------------------------------------------------ inputs

TICKER_PATTERN = r"^[A-Z0-9.\-\^=]{1,15}$"


def _normalize_ticker(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


Ticker = Annotated[
    str,
    BeforeValidator(_normalize_ticker),
    Field(
        pattern=TICKER_PATTERN,
        description="Ticker symbol, case-insensitive. Share classes use a dash.",
        examples=["AAPL", "BRK-B", "^GSPC", "BTC-USD", "EURUSD=X"],
    ),
]
Tickers = Annotated[
    list[Ticker],
    Field(min_length=1, max_length=10, description="1 to 10 ticker symbols."),
]
StartDate = Annotated[
    date, Field(description="Start date, YYYY-MM-DD.", examples=["2024-01-02"])
]
EndDate = Annotated[
    date | None,
    Field(
        description="End date, YYYY-MM-DD, inclusive. Defaults to today.",
        examples=["2024-12-31"],
    ),
]
Interval = Literal["1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]
ResponseFormat = Literal["summary", "rows"]
MaxRows = Annotated[
    int,
    Field(
        ge=1,
        le=1000,
        description="Row cap for response_format='rows'. Longer series are "
        "downsampled evenly and flagged as truncated.",
    ),
]
Window = Annotated[int, Field(ge=2, le=500, description="Lookback window in bars.")]

INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h"})

# Yahoo limits as enforced by yfinance 1.8: (max span per request, max lookback), days.
INTRADAY_LIMITS: dict[str, tuple[int | None, int]] = {
    "1m": (7, 30),
    "5m": (None, 60),
    "15m": (None, 60),
    "30m": (None, 60),
    "1h": (None, 730),
}


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive


def resolve_range(
    start: date, end: date | None, interval: str = "1d", today: date | None = None
) -> DateRange:
    """Validate a date range against ordering rules and Yahoo's intraday limits."""
    today = today or date.today()
    end = end or today
    if start > today:
        raise invalid_input(
            f"start_date {start} is in the future. Use a date on or before {today}."
        )
    if start >= end:
        raise invalid_input(
            f"start_date ({start}) must be before end_date ({end}). "
            "Swap them or widen the range."
        )
    if interval in INTRADAY_LIMITS:
        max_span, max_lookback = INTRADAY_LIMITS[interval]
        if max_span is not None and (end - start).days > max_span:
            raise invalid_input(
                f"interval '{interval}' allows at most {max_span} days per request, "
                f"got {(end - start).days}. Shorten the range or use a coarser "
                "interval such as '5m' or '1h'."
            )
        earliest = today - timedelta(days=max_lookback)
        if start < earliest:
            raise invalid_input(
                f"interval '{interval}' data only goes back {max_lookback} days "
                f"(to {earliest}). Move start_date later or use a coarser interval "
                "such as '1d'."
            )
    return DateRange(start, end)


# ----------------------------------------------------------------- outputs


class Quote(BaseModel):
    ticker: str
    last_price: float | None = Field(description="Latest trade price.")
    previous_close: float | None
    change: float | None = Field(description="last_price - previous_close.")
    change_pct: float | None = Field(description="Fraction: 0.012 means +1.2%.")
    currency: str | None
    market_cap: float | None
    shares_outstanding: float | None
    exchange: str | None
    fetched_at: str = Field(description="UTC time of the request, ISO 8601.")


class HistorySummary(BaseModel):
    rows: int
    first_date: str
    last_date: str
    first_close: float | None
    last_close: float | None
    period_return: float | None = Field(
        description="last_close / first_close - 1, as a fraction."
    )
    min_close: float | None
    min_close_date: str | None
    max_close: float | None
    max_close_date: str | None
    avg_volume: float | None


class PriceRow(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


class TickerHistory(BaseModel):
    ticker: str
    summary: HistorySummary
    rows: list[PriceRow] | None = Field(
        default=None, description="Present only when response_format='rows'."
    )
    truncated: bool = False
    total_rows: int


class PriceHistoryResult(BaseModel):
    start_date: str
    end_date: str
    interval: str
    adjusted: bool
    response_format: str
    results: list[TickerHistory]


class CompanyInfo(BaseModel):
    ticker: str
    name: str | None
    quote_type: str | None
    exchange: str | None
    sector: str | None
    industry: str | None
    currency: str | None
    country: str | None
    website: str | None
    employees: int | None


class DatedValue(BaseModel):
    date: str
    value: float


class DividendsResult(BaseModel):
    ticker: str
    start_date: str | None
    count: int
    total: float = Field(description="Sum of the listed dividends per share.")
    dividends: list[DatedValue] = Field(
        description="Cash dividend per share by ex-date, oldest first."
    )


class SplitsResult(BaseModel):
    ticker: str
    count: int
    splits: list[DatedValue] = Field(
        description="Split ratio (new shares per old share) by date, oldest first."
    )


# ------------------------------------------------------------ fundamentals

Statement = Literal["income_statement", "balance_sheet", "cash_flow"]
Period = Literal["annual", "quarterly"]
FundamentalMetric = Literal[
    "gross_margin",
    "operating_margin",
    "net_margin",
    "ebitda",
    "debt_to_equity",
    "liabilities_to_equity",
    "current_ratio",
    "quick_ratio",
    "free_cash_flow",
    "fcf_margin",
    "operating_cash_flow_margin",
    "roe",
    "roa",
    "book_value_per_share",
    "pe_ratio",
    "pb_ratio",
    "dividend_yield",
]


class FiscalPeriod(BaseModel):
    period_end: str
    fields: dict[str, float | None] = Field(
        description="Canonical field -> value in the reporting currency (EPS per "
        "share, share counts in shares). null when not reported."
    )


class FinancialStatementResult(BaseModel):
    ticker: str
    statement: str
    period: str
    currency: str | None = Field(description="Reporting currency of the statement.")
    fiscal_periods: list[FiscalPeriod] = Field(description="Newest first.")
    missing_fields: list[str] = Field(
        description="Canonical fields with no matching label in any period."
    )
    unmapped_labels: list[str] = Field(
        description="yfinance labels not mapped to a canonical field."
    )
    notes: list[str]


class AsOfPrice(BaseModel):
    price: float | None
    currency: str | None
    fetched_at: str
    applies_to_period_end: str | None = Field(
        description="Market-based ratios are computed for this (latest) period only."
    )


class FundamentalsPeriod(BaseModel):
    period_end: str
    metrics: dict[str, float | None]


class FundamentalsResult(BaseModel):
    ticker: str
    currency: str | None = Field(description="Reporting currency of the statements.")
    period: str
    as_of_price: AsOfPrice | None = Field(
        description="Present when pe_ratio, pb_ratio or dividend_yield was requested."
    )
    periods: list[FundamentalsPeriod] = Field(description="Newest first.")
    inputs_used: dict[str, dict[str, float | None]] = Field(
        description="period_end -> canonical inputs the requested metrics read."
    )
    notes: list[str]


# ---------------------------------------------------------------- analysis

Indicator = Literal[
    "sma", "ema", "rsi", "macd", "volatility", "bollinger_bands", "atr", "stochastic"
]
FastPeriod = Annotated[int, Field(ge=2, le=200, description="MACD fast EMA span.")]
SlowPeriod = Annotated[int, Field(ge=3, le=500, description="MACD slow EMA span.")]
SignalPeriod = Annotated[int, Field(ge=2, le=100, description="MACD signal EMA span.")]
NumStd = Annotated[
    float, Field(ge=0.5, le=5.0, description="Bollinger band width in std devs.")
]
ShortWindow = Annotated[int, Field(ge=2, le=200, description="Short SMA window, days.")]
LongWindow = Annotated[int, Field(ge=3, le=500, description="Long SMA window, days.")]
CostBps = Annotated[
    float,
    Field(ge=0, le=100, description="Cost per entry and per exit, basis points."),
]
RiskFreeRate = Annotated[
    float, Field(ge=0, le=0.2, description="Annual risk-free rate, fraction.")
]


class SeriesSummary(BaseModel):
    latest: float | None
    latest_date: str | None
    min: float | None
    min_date: str | None
    max: float | None
    max_date: str | None


class IndicatorResult(BaseModel):
    ticker: str
    indicator: str
    interval: str
    start_date: str
    end_date: str
    params: dict[str, int | float]
    last_close: float | None
    summary: dict[str, SeriesSummary] = Field(
        description="Per output series: latest value plus min/max over the range."
    )
    response_format: str
    rows: list[dict[str, float | str | None]] | None = Field(
        default=None, description="date, close and each series; rows format only."
    )
    truncated: bool = False
    total_rows: int
    notes: list[str]


class GrowthResult(BaseModel):
    values: list[float]
    periods_per_year: int
    period_growth_rates: list[float | None] = Field(
        description="(curr - prev) / |prev| per step, fraction; null if prev is 0."
    )
    cagr: float | None = Field(description="Compound annual growth rate, fraction.")
    notes: list[str]


class BacktestTrade(BaseModel):
    signal_date: str = Field(description="Close of the bar where the buy signal fired.")
    entry_date: str = Field(description="Fill date: the next bar's open.")
    entry_price: float | None
    exit_signal_date: str | None
    exit_date: str | None
    exit_price: float | None
    return_: float | None = Field(
        alias="return", serialization_alias="return", description="Net of costs."
    )
    open_at_end: bool

    model_config = {"populate_by_name": True}


class BacktestResult(BaseModel):
    ticker: str
    start_date: str
    end_date: str
    bars: int
    short_window: int
    long_window: int
    cost_bps: float
    risk_free_rate: float
    adjusted: bool
    total_return: float | None = Field(description="Fraction, net of costs.")
    buy_and_hold_return: float | None
    excess_return: float | None
    cagr: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    max_drawdown: float | None = Field(
        description="Worst peak-to-trough, fraction <= 0."
    )
    max_drawdown_start: str | None
    max_drawdown_end: str | None
    num_trades: int = Field(description="Completed round trips.")
    win_rate: float | None
    avg_trade_return: float | None
    exposure: float | None = Field(description="Fraction of bars holding a position.")
    trades: list[BacktestTrade]
    buy_signal_dates: list[str]
    sell_signal_dates: list[str]
    notes: list[str]
