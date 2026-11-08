"""Financial statement fetch and label normalization.

yfinance row labels vary by company and version, so each canonical field has an
ordered list of candidate labels (first match wins). The candidates were built
from the labels yfinance 1.8 returns for AAPL, MSFT, KO, JPM, NVDA and TSLA.
Labels that no canonical field claims are reported as `unmapped_labels`.
"""

from dataclasses import dataclass, field
from functools import partial

import anyio
import pandas as pd
import yfinance as yf

from tearsheet.data.cache import STATEMENT_TTL, TTLCache
from tearsheet.data.market import gather, raise_not_found, run_yf, ticker_exists
from tearsheet.errors import invalid_input
from tearsheet.serialize import num

LABELS: dict[str, dict[str, list[str]]] = {
    "income_statement": {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "Total Operating Income As Reported"],
        "net_income": ["Net Income", "Net Income Common Stockholders"],
        "ebitda": ["EBITDA", "Normalized EBITDA"],
        "diluted_eps": ["Diluted EPS"],
        "diluted_shares": ["Diluted Average Shares"],
    },
    "balance_sheet": {
        "total_assets": ["Total Assets"],
        "total_liabilities": [
            "Total Liabilities Net Minority Interest",
            "Total Liabilities",
        ],
        "stockholders_equity": ["Stockholders Equity", "Common Stock Equity"],
        "current_assets": ["Current Assets"],
        "current_liabilities": ["Current Liabilities"],
        "inventory": ["Inventory"],
        "total_debt": ["Total Debt"],
        "cash_and_equivalents": ["Cash And Cash Equivalents", "Cash Financial"],
        "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
    },
    "cash_flow": {
        "operating_cash_flow": [
            "Operating Cash Flow",
            "Cash Flow From Continuing Operating Activities",
        ],
        "capital_expenditure": ["Capital Expenditure", "Purchase Of PPE"],
        "free_cash_flow": ["Free Cash Flow"],
        "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
        "depreciation_and_amortization": [
            "Depreciation And Amortization",
            "Depreciation Amortization Depletion",
        ],
    },
}

FIELD_STATEMENT = {f: st for st, fields in LABELS.items() for f in fields}

# Labels used only to derive a missing canonical field.
TOTAL_EQUITY_LABEL = "Total Equity Gross Minority Interest"

_ATTRS = {
    ("income_statement", "annual"): "financials",
    ("income_statement", "quarterly"): "quarterly_financials",
    ("balance_sheet", "annual"): "balance_sheet",
    ("balance_sheet", "quarterly"): "quarterly_balance_sheet",
    ("cash_flow", "annual"): "cashflow",
    ("cash_flow", "quarterly"): "quarterly_cashflow",
}

_statement_cache = TTLCache()
_currency_cache = TTLCache()


@dataclass
class FiscalPeriodFields:
    period_end: str
    fields: dict[str, float | None]


@dataclass
class NormalizedStatement:
    statement: str
    period: str
    periods: list[FiscalPeriodFields]  # newest first
    unmapped_labels: list[str]
    missing_fields: list[str]
    notes: list[str] = field(default_factory=list)


def _value(df: pd.DataFrame, label: str, col) -> float | None:
    v = df.at[label, col]
    if isinstance(v, pd.Series):  # duplicate labels: take the first non-null
        v = v.dropna().iloc[0] if v.notna().any() else None
    return num(v)


def _first(
    df: pd.DataFrame, candidates: list[str], labels: list[str], col
) -> float | None:
    """Value of the first candidate label that is present and non-null."""
    for label in candidates:
        if label in labels and (v := _value(df, label, col)) is not None:
            return v
    return None


def normalize_statement(
    df: pd.DataFrame, statement: str, period: str
) -> NormalizedStatement:
    """Map a yfinance statement frame (labels x period-end columns) to canonical fields."""
    mapping = LABELS[statement]
    labels = [str(i) for i in df.index]
    used: set[str] = set()
    for candidates in mapping.values():
        used.update(c for c in candidates if c in labels)

    cols = sorted(df.columns, key=pd.Timestamp, reverse=True)
    periods: list[FiscalPeriodFields] = []
    notes: list[str] = []
    for col in cols:
        values: dict[str, float | None] = {}
        for name, candidates in mapping.items():
            values[name] = _first(df, candidates, labels, col)
        end = pd.Timestamp(col).strftime("%Y-%m-%d")
        if (
            statement == "balance_sheet"
            and values["total_liabilities"] is None
            and values["total_assets"] is not None
            and TOTAL_EQUITY_LABEL in labels
            and (equity := _value(df, TOTAL_EQUITY_LABEL, col)) is not None
        ):
            values["total_liabilities"] = num(values["total_assets"] - equity)
            used.add(TOTAL_EQUITY_LABEL)
            notes.append(
                f"{end}: total_liabilities derived as total assets minus "
                f"'{TOTAL_EQUITY_LABEL}'."
            )
        if any(v is not None for v in values.values()):
            periods.append(FiscalPeriodFields(end, values))

    missing = [name for name in mapping if all(p.fields[name] is None for p in periods)]
    return NormalizedStatement(
        statement=statement,
        period=period,
        periods=periods,
        unmapped_labels=sorted(set(labels) - used),
        missing_fields=missing,
        notes=notes,
    )


async def get_statement_frame(ticker: str, statement: str, period: str) -> pd.DataFrame:
    """Raw yfinance statement frame, cached. Raises ToolError if Yahoo has none."""
    attr = _ATTRS.get((statement, period))
    if attr is None:
        raise invalid_input(f"Unknown statement/period: {statement}/{period}.")

    async def load() -> pd.DataFrame:
        df = await run_yf(ticker, lambda: getattr(yf.Ticker(ticker), attr))
        if df is None or df.empty:
            exists = await anyio.to_thread.run_sync(partial(ticker_exists, ticker))
            if not exists:
                await raise_not_found(ticker)
            raise invalid_input(
                f"Yahoo has no {period} {statement.replace('_', ' ')} for '{ticker}'. "
                "Funds, indexes, currencies and crypto have no financial statements."
            )
        return df

    return await _statement_cache.get_or_load(
        (ticker, statement, period), STATEMENT_TTL, load
    )


async def get_statement(
    ticker: str, statement: str, period: str
) -> NormalizedStatement:
    df = await get_statement_frame(ticker, statement, period)
    return normalize_statement(df, statement, period)


async def get_merged_fields(
    ticker: str, period: str, statements: list[str]
) -> tuple[list[tuple[str, dict[str, float | None]]], list[str]]:
    """Canonical fields from several statements merged by period end, newest first.

    Returns (periods, notes). Statements are fetched concurrently.
    """
    normalized: list[NormalizedStatement] = await gather(
        *(partial(get_statement, ticker, st, period) for st in statements)
    )
    merged: dict[str, dict[str, float | None]] = {}
    notes: list[str] = []
    for ns in normalized:
        notes.extend(ns.notes)
        for p in ns.periods:
            merged.setdefault(p.period_end, {}).update(p.fields)
    ordered = sorted(merged.items(), key=lambda kv: kv[0], reverse=True)
    return ordered, notes


async def get_financial_currency(ticker: str) -> str | None:
    """Reporting currency of the statements (can differ from the quote currency)."""

    async def load() -> dict:
        info = await run_yf(ticker, lambda: yf.Ticker(ticker).info or {})
        return {"currency": info.get("financialCurrency") or info.get("currency")}

    cached = await _currency_cache.get_or_load(
        ("currency", ticker), STATEMENT_TTL, load
    )
    return cached["currency"]


def clear_caches() -> None:
    _statement_cache.clear()
    _currency_cache.clear()
