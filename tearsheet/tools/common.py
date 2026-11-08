"""Fetch-and-compute steps shared by more than one tool wrapper."""

from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

from tearsheet.analysis.ratios import (
    MARKET_METRICS,
    METRIC_FIELDS,
    FundamentalsTable,
    MarketInputs,
    compute_fundamentals,
    ttm_eps,
)
from tearsheet.data import fundamentals, market
from tearsheet.data.fundamentals import FIELD_STATEMENT, LABELS
from tearsheet.models import AsOfPrice


@dataclass
class FundamentalsData:
    table: FundamentalsTable
    currency: str | None
    as_of: AsOfPrice | None
    notes: list[str]


async def load_fundamentals(
    ticker: str, period: str, metrics: list[str]
) -> FundamentalsData:
    """Fetch only the statements (and price/dividends) `metrics` need, then compute."""
    statements = sorted(
        {FIELD_STATEMENT[f] for m in metrics for f in METRIC_FIELDS[m]},
        key=list(LABELS).index,
    )
    periods, currency, notes = [], None, []
    if statements:
        (periods, notes), currency = await market.gather(
            partial(fundamentals.get_merged_fields, ticker, period, statements),
            partial(fundamentals.get_financial_currency, ticker),
        )

    as_of, inputs = None, None
    if any(m in MARKET_METRICS for m in metrics):
        quote, dividends = await market.gather(
            partial(market.get_quote, ticker),
            partial(market.get_dividends, ticker, date.today() - timedelta(days=365)),
        )
        eps, eps_note = ttm_eps(periods, period)
        mismatch = None
        if currency and quote.currency and currency != quote.currency:
            mismatch = (
                f"pe_ratio and pb_ratio: statements are in {currency} but the price "
                f"is in {quote.currency}, so they are not computed."
            )
        inputs = MarketInputs(
            price=quote.last_price,
            eps=eps,
            eps_note=eps_note,
            ttm_dividends=sum(d.value for d in dividends),
            currency_mismatch=mismatch,
        )
        if not periods:
            periods = [(date.today().isoformat(), {})]
        as_of = AsOfPrice(
            price=quote.last_price,
            currency=quote.currency,
            fetched_at=quote.fetched_at,
            applies_to_period_end=periods[0][0],
        )

    return FundamentalsData(
        compute_fundamentals(periods, metrics, inputs), currency, as_of, notes
    )
