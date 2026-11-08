"""Financial ratios as pure functions over canonical statement fields.

Each function takes a mapping of canonical field -> value (see
tearsheet/data/fundamentals.py) and returns a Ratio: the value (or None when an
input is missing or a denominator is zero), the inputs used, and an optional note.
Margins and returns are fractions: 0.25 means 25%.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

Fields = Mapping[str, float | None]


@dataclass(frozen=True)
class Ratio:
    value: float | None
    inputs: dict[str, float | None]
    notes: list[str] = field(default_factory=list)


def _div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pick(f: Fields, *names: str) -> dict[str, float | None]:
    return {n: f.get(n) for n in names}


def _simple(numerator: str, denominator: str) -> Callable[[Fields], Ratio]:
    def ratio(f: Fields) -> Ratio:
        inputs = _pick(f, numerator, denominator)
        return Ratio(_div(inputs[numerator], inputs[denominator]), inputs)

    return ratio


def gross_margin(f: Fields) -> Ratio:
    if f.get("gross_profit") is not None:
        inputs = _pick(f, "gross_profit", "revenue")
        return Ratio(_div(inputs["gross_profit"], inputs["revenue"]), inputs)
    inputs = _pick(f, "revenue", "cost_of_revenue")
    rev, cor = inputs["revenue"], inputs["cost_of_revenue"]
    value = _div(rev - cor, rev) if rev is not None and cor is not None else None
    return Ratio(
        value,
        inputs,
        ["gross_margin computed as (revenue - cost_of_revenue) / revenue."]
        if value is not None
        else [],
    )


def ebitda(f: Fields) -> Ratio:
    if f.get("ebitda") is not None:
        return Ratio(f["ebitda"], _pick(f, "ebitda"))
    inputs = _pick(f, "operating_income", "depreciation_and_amortization")
    oi, da = inputs["operating_income"], inputs["depreciation_and_amortization"]
    value = oi + da if oi is not None and da is not None else None
    return Ratio(
        value,
        inputs,
        ["ebitda computed as operating_income + depreciation_and_amortization."]
        if value is not None
        else [],
    )


def quick_ratio(f: Fields) -> Ratio:
    inputs = _pick(f, "current_assets", "inventory", "current_liabilities")
    ca, inv, cl = (
        inputs["current_assets"],
        inputs["inventory"],
        inputs["current_liabilities"],
    )
    notes = []
    if inv is None and ca is not None:
        inv = 0.0
        notes.append("quick_ratio: inventory not reported, treated as 0.")
    value = _div(ca - inv, cl) if ca is not None and inv is not None else None
    return Ratio(value, inputs, notes)


def free_cash_flow(f: Fields) -> Ratio:
    """operating_cash_flow - |capital_expenditure|. yfinance reports capex as negative."""
    inputs = _pick(f, "operating_cash_flow", "capital_expenditure", "free_cash_flow")
    ocf, capex, reported = (
        inputs["operating_cash_flow"],
        inputs["capital_expenditure"],
        inputs["free_cash_flow"],
    )
    if ocf is None or capex is None:
        if reported is not None:
            return Ratio(
                reported,
                inputs,
                ["free_cash_flow: capex or OCF missing, used reported value."],
            )
        return Ratio(None, inputs)
    value = ocf - abs(capex)
    notes = []
    if reported is not None and abs(reported - value) > 0.01 * max(abs(value), 1.0):
        notes.append(
            f"free_cash_flow: computed {value:,.0f} differs from reported {reported:,.0f}."
        )
    return Ratio(value, inputs, notes)


def fcf_margin(f: Fields) -> Ratio:
    fcf = free_cash_flow(f)
    inputs = {**fcf.inputs, "revenue": f.get("revenue")}
    return Ratio(_div(fcf.value, inputs["revenue"]), inputs, fcf.notes)


def book_value_per_share(f: Fields) -> Ratio:
    return _simple("stockholders_equity", "shares_outstanding")(f)


STATEMENT_METRICS: dict[str, Callable[[Fields], Ratio]] = {
    "gross_margin": gross_margin,
    "operating_margin": _simple("operating_income", "revenue"),
    "net_margin": _simple("net_income", "revenue"),
    "ebitda": ebitda,
    "debt_to_equity": _simple("total_debt", "stockholders_equity"),
    "liabilities_to_equity": _simple("total_liabilities", "stockholders_equity"),
    "current_ratio": _simple("current_assets", "current_liabilities"),
    "quick_ratio": quick_ratio,
    "free_cash_flow": free_cash_flow,
    "fcf_margin": fcf_margin,
    "operating_cash_flow_margin": _simple("operating_cash_flow", "revenue"),
    "roe": _simple("net_income", "stockholders_equity"),
    "roa": _simple("net_income", "total_assets"),
    "book_value_per_share": book_value_per_share,
}

# Canonical fields each metric may read, used to decide which statements to fetch.
METRIC_FIELDS: dict[str, tuple[str, ...]] = {
    "gross_margin": ("gross_profit", "revenue", "cost_of_revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
    "ebitda": ("ebitda", "operating_income", "depreciation_and_amortization"),
    "debt_to_equity": ("total_debt", "stockholders_equity"),
    "liabilities_to_equity": ("total_liabilities", "stockholders_equity"),
    "current_ratio": ("current_assets", "current_liabilities"),
    "quick_ratio": ("current_assets", "inventory", "current_liabilities"),
    "free_cash_flow": ("operating_cash_flow", "capital_expenditure", "free_cash_flow"),
    "fcf_margin": (
        "operating_cash_flow",
        "capital_expenditure",
        "free_cash_flow",
        "revenue",
    ),
    "operating_cash_flow_margin": ("operating_cash_flow", "revenue"),
    "roe": ("net_income", "stockholders_equity"),
    "roa": ("net_income", "total_assets"),
    "book_value_per_share": ("stockholders_equity", "shares_outstanding"),
    "pe_ratio": ("diluted_eps",),
    "pb_ratio": ("stockholders_equity", "shares_outstanding"),
    "dividend_yield": (),
}

MARKET_METRICS = ("pe_ratio", "pb_ratio", "dividend_yield")

# How each metric's value reads: percent (fraction shown as %), multiple (x times),
# amount (reporting currency) or per_share (currency per share).
METRIC_UNITS: dict[str, str] = {
    "gross_margin": "percent",
    "operating_margin": "percent",
    "net_margin": "percent",
    "fcf_margin": "percent",
    "operating_cash_flow_margin": "percent",
    "roe": "percent",
    "roa": "percent",
    "dividend_yield": "percent",
    "debt_to_equity": "multiple",
    "liabilities_to_equity": "multiple",
    "current_ratio": "multiple",
    "quick_ratio": "multiple",
    "pe_ratio": "multiple",
    "pb_ratio": "multiple",
    "ebitda": "amount",
    "free_cash_flow": "amount",
    "book_value_per_share": "per_share",
}
ALL_METRICS = tuple(STATEMENT_METRICS) + MARKET_METRICS


# ------------------------------------------------- market-based (latest only)


def pe_ratio(price: float | None, diluted_eps: float | None) -> Ratio:
    inputs = {"price": price, "diluted_eps": diluted_eps}
    if diluted_eps is not None and diluted_eps <= 0:
        return Ratio(None, inputs, ["pe_ratio: undefined because diluted EPS <= 0."])
    return Ratio(_div(price, diluted_eps), inputs)


def pb_ratio(price: float | None, f: Fields) -> Ratio:
    bvps = book_value_per_share(f)
    inputs = {"price": price, **bvps.inputs, "book_value_per_share": bvps.value}
    if bvps.value is not None and bvps.value <= 0:
        return Ratio(
            None, inputs, ["pb_ratio: undefined because book value per share <= 0."]
        )
    return Ratio(_div(price, bvps.value), inputs)


def dividend_yield(price: float | None, ttm_dividends: float | None) -> Ratio:
    inputs = {"price": price, "ttm_dividends_per_share": ttm_dividends}
    return Ratio(_div(ttm_dividends, price), inputs)


# ------------------------------------------------------------- assembly

CURRENCY_METRICS = {"ebitda", "free_cash_flow"}


@dataclass(frozen=True)
class MarketInputs:
    price: float | None
    eps: float | None  # latest annual diluted EPS, or TTM sum for quarterly
    eps_note: str | None
    ttm_dividends: float | None
    currency_mismatch: str | None  # message when quote and reporting currency differ


@dataclass
class FundamentalsTable:
    periods: list[tuple[str, dict[str, float | None]]]  # newest first
    inputs_used: dict[str, dict[str, float | None]]
    notes: list[str]


def ttm_eps(
    periods: list[tuple[str, Fields]], period: str
) -> tuple[float | None, str | None]:
    """EPS for P/E: latest annual diluted EPS, or the sum of the last 4 quarters."""
    eps = [f.get("diluted_eps") for _, f in periods]
    if period == "annual":
        return (eps[0] if eps else None), None
    last4 = [e for e in eps[:4] if e is not None]
    if len(last4) < 4:
        return (
            None,
            "pe_ratio: fewer than 4 quarters of diluted EPS, cannot form TTM EPS.",
        )
    return sum(
        last4
    ), "pe_ratio uses trailing-twelve-month EPS (sum of last 4 quarters)."


def compute_fundamentals(
    periods: list[tuple[str, Fields]],
    metrics: list[str],
    market: MarketInputs | None,
) -> FundamentalsTable:
    """Evaluate `metrics` for every period. Market metrics fill the latest period only."""
    notes_by_text: dict[str, list[str]] = {}
    rows: list[tuple[str, dict[str, float | None]]] = []
    inputs_used: dict[str, dict[str, float | None]] = {}

    def note(text: str, period_end: str) -> None:
        ends = notes_by_text.setdefault(text, [])
        if period_end not in ends:
            ends.append(period_end)

    for i, (period_end, f) in enumerate(periods):
        values: dict[str, float | None] = {}
        used: dict[str, float | None] = {}
        for m in metrics:
            if m in STATEMENT_METRICS:
                r = STATEMENT_METRICS[m](f)
            elif i > 0 or market is None:
                values[m] = None
                continue
            elif market.currency_mismatch and m in ("pe_ratio", "pb_ratio"):
                values[m] = None
                note(market.currency_mismatch, period_end)
                continue
            elif m == "pe_ratio":
                r = pe_ratio(market.price, market.eps)
                if market.eps_note:
                    note(market.eps_note, period_end)
            elif m == "pb_ratio":
                r = pb_ratio(market.price, f)
            else:
                r = dividend_yield(market.price, market.ttm_dividends)
            values[m] = r.value
            used.update(r.inputs)
            for text in r.notes:
                note(text, period_end)
            missing = [k for k, v in r.inputs.items() if v is None]
            if r.value is None and not r.notes and missing:
                note(
                    f"{m}: null because {', '.join(missing)} not reported.", period_end
                )
        rows.append((period_end, values))
        inputs_used[period_end] = used

    notes = [
        text if len(ends) == len(periods) else f"{text} (periods: {', '.join(ends)})"
        for text, ends in notes_by_text.items()
    ]
    return FundamentalsTable(rows, inputs_used, notes)
