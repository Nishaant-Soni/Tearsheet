"""Growth rates for short series such as annual revenue or EPS."""

import math
from dataclasses import dataclass, field


@dataclass
class Growth:
    period_growth_rates: list[float | None]
    cagr: float | None
    notes: list[str] = field(default_factory=list)


def calculate_growth_rates(values: list[float], periods_per_year: int = 1) -> Growth:
    """Period-over-period growth and compound annual growth rate.

    Period growth is (curr - prev) / |prev|, so a move from -50 to -25 is +0.5;
    None when prev is 0. CAGR = (last / first) ** (periods_per_year / (n - 1)) - 1,
    None when first or last is <= 0 (undefined across sign changes). Fractions.
    """
    notes: list[str] = []
    rates: list[float | None] = []
    for prev, curr in zip(values, values[1:]):
        rates.append(None if prev == 0 else (curr - prev) / abs(prev))
    if any(prev == 0 for prev in values[:-1]):
        notes.append("Period growth is null where the previous value is 0.")

    cagr = None
    if len(values) < 2:
        notes.append("CAGR needs at least two values.")
    elif values[0] <= 0 or values[-1] <= 0:
        notes.append(
            "CAGR is undefined when the first or last value is zero or negative "
            "(a sign change has no compound growth rate)."
        )
    else:
        cagr = (values[-1] / values[0]) ** (periods_per_year / (len(values) - 1)) - 1
        if not math.isfinite(cagr):
            cagr = None
    return Growth(rates, cagr, notes)
