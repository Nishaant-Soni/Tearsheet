"""Fetch-and-compute steps shared by more than one tool wrapper."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial

from tearsheet.analysis.ratios import (
    MARKET_METRICS,
    METRIC_FIELDS,
    FundamentalsTable,
    MarketInputs,
    compute_fundamentals,
)
from tearsheet.data import fundamentals, market
from tearsheet.data.fundamentals import FIELD_STATEMENT, LABELS
from tearsheet.models import AsOfPrice

_DATED_NOTE = re.compile(r"^(\d{4}-\d{2}-\d{2}): ")


@dataclass
class FundamentalsData:
    table: FundamentalsTable
    currency: str | None
    as_of: AsOfPrice | None
    statement_notes: list[str]  # derived-field notes, "YYYY-MM-DD: ..." when dated
    partial: dict[str, str] = field(default_factory=dict)  # period end -> note

    def notes_for(self, keep: set[str]) -> list[str]:
        """Every note that concerns a period in `keep` (dropped periods stay silent)."""
        dated = [
            n
            for n in self.statement_notes
            if (m := _DATED_NOTE.match(n)) is None or m.group(1) in keep
        ]
        partial_notes = [note for end, note in self.partial.items() if end in keep]
        return [*dated, *partial_notes, *self.table.notes_for(keep)]


async def load_fundamentals(
    ticker: str, period: str, metrics: list[str]
) -> FundamentalsData:
    """Fetch only the statements (and price/dividends) `metrics` need, then compute."""
    statements = sorted(
        {FIELD_STATEMENT[f] for m in metrics for f in METRIC_FIELDS[m]},
        key=list(LABELS).index,
    )
    periods, currency, statement_notes, partial_notes = [], None, [], {}
    fully_reported = None
    if statements:
        merged, currency = await market.gather(
            partial(fundamentals.get_merged_fields, ticker, period, statements),
            partial(fundamentals.get_financial_currency, ticker),
        )
        periods, statement_notes = merged.periods, merged.notes
        partial_notes = merged.partial_notes()
        fully_reported = {end: merged.complete(end) for end, _ in periods}

    inputs, quote = None, None
    if any(m in MARKET_METRICS for m in metrics):
        quote, dividends = await market.gather(
            partial(market.get_quote, ticker),
            partial(market.get_dividends, ticker, date.today() - timedelta(days=365)),
        )
        mismatch = None
        if currency and quote.currency and currency != quote.currency:
            mismatch = (
                f"pe_ratio and pb_ratio: statements are in {currency} but the price "
                f"is in {quote.currency}, so they are not computed."
            )
        inputs = MarketInputs(
            price=quote.last_price,
            period=period,
            ttm_dividends=sum(d.value for d in dividends),
            currency_mismatch=mismatch,
        )
        if not periods:
            periods = [(date.today().isoformat(), {})]

    table = compute_fundamentals(periods, metrics, inputs, fully_reported)
    as_of = None
    if quote is not None:
        applies_to = {m: table.applies_to[m] for m in metrics if m in table.applies_to}
        as_of = AsOfPrice(
            price=quote.last_price,
            currency=quote.currency,
            fetched_at=quote.fetched_at,
            applies_to_period_end=max(applies_to.values()) if applies_to else None,
            applies_to=applies_to,
        )
    return FundamentalsData(table, currency, as_of, statement_notes, partial_notes)
