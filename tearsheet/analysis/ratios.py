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


# Ratios with equity in the denominator flip sign when equity is negative (common
# after large buybacks, e.g. SBUX, MCD, BKNG), which reads as a loss or as negative
# leverage. They are left undefined instead.
NEGATIVE_EQUITY_METRICS = ("roe", "debt_to_equity", "liabilities_to_equity")


def _over_equity(numerator: str, metric: str) -> Callable[[Fields], Ratio]:
    def ratio(f: Fields) -> Ratio:
        inputs = _pick(f, numerator, "stockholders_equity")
        equity = inputs["stockholders_equity"]
        if equity is not None and equity <= 0:
            return Ratio(
                None,
                inputs,
                [
                    f"{metric}: undefined because stockholders' equity is zero or "
                    f"negative ({equity:,.0f})."
                ],
            )
        return Ratio(_div(inputs[numerator], equity), inputs)

    return ratio


def book_value_per_share(f: Fields) -> Ratio:
    """Kept when negative: it is a factual figure, unlike the ratios above."""
    r = _simple("stockholders_equity", "shares_outstanding")(f)
    if r.value is not None and r.value < 0:
        notes = [
            "book_value_per_share is negative because stockholders' equity is negative."
        ]
        return Ratio(r.value, r.inputs, notes)
    return r


STATEMENT_METRICS: dict[str, Callable[[Fields], Ratio]] = {
    "gross_margin": gross_margin,
    "operating_margin": _simple("operating_income", "revenue"),
    "net_margin": _simple("net_income", "revenue"),
    "ebitda": ebitda,
    "debt_to_equity": _over_equity("total_debt", "debt_to_equity"),
    "liabilities_to_equity": _over_equity("total_liabilities", "liabilities_to_equity"),
    "current_ratio": _simple("current_assets", "current_liabilities"),
    "quick_ratio": quick_ratio,
    "free_cash_flow": free_cash_flow,
    "fcf_margin": fcf_margin,
    "operating_cash_flow_margin": _simple("operating_cash_flow", "revenue"),
    "roe": _over_equity("net_income", "roe"),
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
    period: str  # "annual" or "quarterly", for the EPS used by pe_ratio
    ttm_dividends: float | None
    currency_mismatch: str | None  # message when quote and reporting currency differ


@dataclass
class FundamentalsTable:
    periods: list[tuple[str, dict[str, float | None]]]  # newest first
    inputs_used: dict[str, dict[str, float | None]]
    note_periods: dict[str, list[str]]  # note text -> period ends it applies to
    applies_to: dict[str, str] = field(default_factory=dict)  # market metric -> period

    @property
    def notes(self) -> list[str]:
        return self.notes_for({end for end, _ in self.periods})

    def notes_for(self, keep: set[str]) -> list[str]:
        """Notes for the periods in `keep`, naming periods unless all of them apply."""
        out = []
        for text, ends in self.note_periods.items():
            kept = [e for e in ends if e in keep]
            if not kept:
                continue
            named = all(e in text for e in kept)  # the note already says which period
            out.append(
                text
                if named or len(kept) == len(keep)
                else f"{text} (periods: {', '.join(kept)})"
            )
        return out


def _newest(
    periods: list[tuple[str, Fields]],
    has_inputs: Callable[[Fields], bool],
    reported: Callable[[str], bool],
) -> tuple[int | None, bool]:
    """(index, fully reported) of the newest period with the inputs, preferring periods
    whose statement is fully reported; falls back to any period with the inputs."""
    candidates = [i for i, (_, f) in enumerate(periods) if has_inputs(f)]
    full = [i for i in candidates if reported(periods[i][0])]
    if full:
        return full[0], True
    return (candidates[0], False) if candidates else (None, False)


def pe_eps(
    periods: list[tuple[str, Fields]],
    period: str,
    reported: Callable[[str], bool] = lambda end: True,
) -> tuple[int | None, float | None, str | None]:
    """(period index, EPS, note) for P/E: the newest annual diluted EPS, or TTM EPS from
    4 consecutive quarters ending there. Prefers periods whose income statement is
    fully reported (revenue and net income present), so an EPS figure Yahoo shows
    before the rest of the year is filed is not used."""
    first, full = _newest(periods, lambda f: f.get("diluted_eps") is not None, reported)
    if first is None:
        return None, None, None
    caveat = (
        None
        if full
        else f"pe_ratio uses {periods[first][0]}, whose income statement is only partly "
        "reported; no fully reported period has diluted EPS."
    )
    if period == "annual":
        return first, periods[first][1]["diluted_eps"], caveat
    window = [f.get("diluted_eps") for _, f in periods[first : first + 4]]
    if len(window) < 4 or any(e is None for e in window):
        return (
            first,
            None,
            (
                "pe_ratio: fewer than 4 consecutive quarters of diluted EPS, cannot form "
                "TTM EPS."
            ),
        )
    ttm = f"pe_ratio uses trailing-twelve-month EPS (4 quarters ending {periods[first][0]})."
    return first, sum(window), " ".join(n for n in (ttm, caveat) if n)


def compute_fundamentals(
    periods: list[tuple[str, Fields]],
    metrics: list[str],
    market: MarketInputs | None,
    fully_reported: Mapping[str, set[str]] | None = None,
) -> FundamentalsTable:
    """Evaluate `metrics` for every period.

    Each market metric fills one period: pe_ratio the newest period with diluted EPS,
    pb_ratio the newest with equity and a share count, dividend_yield the newest
    period. Periods whose statement is only partly reported are skipped (an early EPS
    figure, a balance sheet without total assets) unless nothing else has the inputs.
    `fully_reported` maps period end -> statements that fully reported it; None
    treats every period as fully reported.
    """
    note_periods: dict[str, list[str]] = {}
    rows: list[tuple[str, dict[str, float | None]]] = []
    inputs_used: dict[str, dict[str, float | None]] = {}

    def note(text: str, period_end: str) -> None:
        ends = note_periods.setdefault(text, [])
        if period_end not in ends:
            ends.append(period_end)

    def reported(statement: str) -> Callable[[str], bool]:
        if fully_reported is None:
            return lambda end: True
        return lambda end: statement in fully_reported.get(end, set())

    targets: dict[str, int] = {}
    eps_value, eps_note = None, None
    if market is not None and periods:
        pe_index, eps_value, eps_note = pe_eps(
            periods, market.period, reported("income_statement")
        )
        pb_index, pb_full = _newest(
            periods,
            lambda f: (
                f.get("stockholders_equity") is not None
                and f.get("shares_outstanding") is not None
            ),
            reported("balance_sheet"),
        )
        targets = {
            "pe_ratio": pe_index if pe_index is not None else 0,
            "pb_ratio": pb_index if pb_index is not None else 0,
            "dividend_yield": 0,
        }
        if pe_index and "pe_ratio" in metrics and eps_note is None:
            note(
                f"pe_ratio uses {periods[pe_index][0]}, the newest fully reported "
                "period with diluted EPS.",
                periods[pe_index][0],
            )
        if pb_index is not None and "pb_ratio" in metrics:
            if not pb_full:
                note(
                    f"pb_ratio uses {periods[pb_index][0]}, whose balance sheet is only "
                    "partly reported; no fully reported period has equity and shares.",
                    periods[pb_index][0],
                )
            elif pb_index:
                note(
                    f"pb_ratio uses {periods[pb_index][0]}, the newest fully reported "
                    "period with stockholders' equity and shares outstanding.",
                    periods[pb_index][0],
                )

    for i, (period_end, f) in enumerate(periods):
        values: dict[str, float | None] = {}
        used: dict[str, float | None] = {}
        for m in metrics:
            if m in STATEMENT_METRICS:
                r = STATEMENT_METRICS[m](f)
            elif market is None or targets.get(m) != i:
                values[m] = None
                continue
            elif market.currency_mismatch and m in ("pe_ratio", "pb_ratio"):
                values[m] = None
                note(market.currency_mismatch, period_end)
                continue
            elif m == "pe_ratio":
                r = pe_ratio(market.price, eps_value)
                if eps_note:
                    note(eps_note, period_end)
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

    applies_to = {
        m: periods[targets[m]][0] for m in metrics if m in targets and periods
    }
    return FundamentalsTable(rows, inputs_used, note_periods, applies_to)
