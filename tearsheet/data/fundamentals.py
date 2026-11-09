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
        # Falls back to issued minus treasury shares: see _shares_outstanding.
        "shares_outstanding": ["Ordinary Shares Number"],
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
SHARES_ISSUED_LABEL = "Share Issued"  # includes treasury shares
TREASURY_SHARES_LABEL = "Treasury Shares Number"
# Read only by fallbacks, but known: never reported as unmapped, used or not.
FALLBACK_LABELS = (TOTAL_EQUITY_LABEL, SHARES_ISSUED_LABEL, TREASURY_SHARES_LABEL)

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
    # period end -> fields present, for periods lacking this statement's core fields
    partial_periods: dict[str, list[str]] = field(default_factory=dict)


# A statement counts as having reported a period only if these are present. Yahoo can
# show a column early with a few values (e.g. diluted EPS from an earnings release).
CORE_FIELDS = {
    "income_statement": ("revenue", "net_income"),
    "balance_sheet": ("total_assets", "stockholders_equity"),
    "cash_flow": ("operating_cash_flow",),
}


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


def _shares_outstanding(
    df: pd.DataFrame, labels: list[str], col, end: str
) -> tuple[float | None, str]:
    """Fallback when "Ordinary Shares Number" is missing: (value, note).

    "Share Issued" counts treasury shares, so subtract them when Yahoo reports them.
    Yahoo omits the treasury line for companies that hold none (they retire bought-
    back shares; issued equals ordinary for AAPL, MSFT, NVDA, TSLA, SBUX, TSM), so
    issued shares alone are used then, with a note.
    """
    issued = (
        _value(df, SHARES_ISSUED_LABEL, col) if SHARES_ISSUED_LABEL in labels else None
    )
    treasury = (
        _value(df, TREASURY_SHARES_LABEL, col)
        if TREASURY_SHARES_LABEL in labels
        else None
    )
    if issued is None:
        return (
            None,
            f"{end}: shares_outstanding not reported (no ordinary or issued share count).",
        )
    if treasury is not None:
        return (
            num(issued - abs(treasury)),
            f"{end}: shares_outstanding derived as shares issued minus treasury shares.",
        )
    return (
        issued,
        f"{end}: shares_outstanding taken from shares issued; Yahoo reports no "
        "treasury shares for this period.",
    )


def normalize_statement(
    df: pd.DataFrame, statement: str, period: str
) -> NormalizedStatement:
    """Map a yfinance statement frame (labels x period-end columns) to canonical fields."""
    mapping = LABELS[statement]
    labels = [str(i) for i in df.index]
    used: set[str] = set()
    for candidates in mapping.values():
        used.update(c for c in candidates if c in labels)
    used.update(label for label in FALLBACK_LABELS if label in labels)

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
            notes.append(
                f"{end}: total_liabilities derived as total assets minus "
                f"'{TOTAL_EQUITY_LABEL}'."
            )
        if (
            statement == "balance_sheet"
            and values["shares_outstanding"] is None
            and any(v is not None for v in values.values())
        ):
            shares, note = _shares_outstanding(df, labels, col, end)
            values["shares_outstanding"] = shares
            notes.append(note)
        if any(v is not None for v in values.values()):
            periods.append(FiscalPeriodFields(end, values))

    missing = [name for name in mapping if all(p.fields[name] is None for p in periods)]
    partial = {
        p.period_end: [k for k, v in p.fields.items() if v is not None]
        for p in periods
        if any(p.fields[c] is None for c in CORE_FIELDS[statement])
    }
    return NormalizedStatement(
        statement=statement,
        period=period,
        periods=periods,
        unmapped_labels=sorted(set(labels) - used),
        missing_fields=missing,
        notes=notes,
        partial_periods=partial,
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


STATEMENT_NAMES = {
    "income_statement": "the income statement",
    "balance_sheet": "the balance sheet",
    "cash_flow": "the cash flow statement",
}


def _names(statements: list[str]) -> str:
    return " and ".join(STATEMENT_NAMES[s] for s in statements)


def _verb(statements: list[str]) -> str:
    return "are" if len(statements) > 1 else "is"


@dataclass
class MergedFields:
    periods: list[tuple[str, dict[str, float | None]]]  # newest first
    sources: dict[str, list[str]]  # period end -> statements that have the column
    statements: list[str]  # statements requested
    notes: list[str]  # statement-level notes (derived fields)
    # (period end, statement) -> fields present, where the core fields are missing
    partly: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def complete(self, end: str) -> set[str]:
        """Statements that fully reported `end` (column present with core fields)."""
        return {s for s in self.sources.get(end, []) if (end, s) not in self.partly}

    def partial_notes(self) -> dict[str, str]:
        """Period end -> note, for periods any requested statement did not fully report.

        Periods newer than the newest complete one are "reported so far" (filing in
        progress); older ones have aged out of a statement's Yahoo window.
        """
        complete = [
            e for e, _ in self.periods if len(self.complete(e)) == len(self.statements)
        ]
        newest_complete = complete[0] if complete else None
        out = {}
        for end, _ in self.periods:
            full = [s for s in self.statements if s in self.complete(end)]
            if len(full) == len(self.statements):
                continue
            newer = newest_complete is None or end > newest_complete
            partly = [s for s in self.statements if (end, s) in self.partly]
            if not partly:
                where = (
                    "reported so far"
                    if newer
                    else "available from Yahoo for this period"
                )
                out[end] = (
                    f"{end}: only {_names(full)} {_verb(full)} {where}; metrics needing "
                    "other statements are null."
                )
                continue
            so_far = " so far" if newer else ""
            pieces = [
                f"{STATEMENT_NAMES[s]} is only partly reported{so_far} "
                f"({', '.join(self.partly[(end, s)])})"
                for s in partly
            ]
            if full:
                pieces.insert(0, f"{_names(full)} {_verb(full)} reported")
            absent = [s for s in self.statements if s not in self.sources.get(end, [])]
            if absent:
                missing = (
                    "not reported yet"
                    if newer
                    else "not available from Yahoo for this period"
                )
                pieces.append(f"{_names(absent)} {_verb(absent)} {missing}")
            out[end] = (
                f"{end}: {'; '.join(pieces)}; metrics needing the missing data are null."
            )
        return out


async def get_merged_fields(
    ticker: str, period: str, statements: list[str]
) -> MergedFields:
    """Canonical fields from several statements merged by period end, newest first.

    Statements are fetched concurrently. `sources` records which statements reported
    each period end, so partially reported periods can be explained.
    """
    normalized: list[NormalizedStatement] = await gather(
        *(partial(get_statement, ticker, st, period) for st in statements)
    )
    merged: dict[str, dict[str, float | None]] = {}
    sources: dict[str, list[str]] = {}
    partly: dict[tuple[str, str], list[str]] = {}
    notes: list[str] = []
    for ns in normalized:
        notes.extend(ns.notes)
        for p in ns.periods:
            merged.setdefault(p.period_end, {}).update(p.fields)
            sources.setdefault(p.period_end, []).append(ns.statement)
        for end, present in ns.partial_periods.items():
            partly[(end, ns.statement)] = present
    ordered = sorted(merged.items(), key=lambda kv: kv[0], reverse=True)
    return MergedFields(ordered, sources, list(statements), notes, partly)


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
