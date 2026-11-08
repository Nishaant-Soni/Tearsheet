def calculate_growth_rates(series: list) -> dict:
    """
    Calculates growth rates for a time series (e.g., revenue, earnings).
    Args:
        series: List of numbers ordered oldest to newest.
    Returns:
        Dict with annualized growth rate and list of period-over-period growth rates.
    """
    growth_rates = []
    try:
        for i in range(1, len(series)):
            prev = series[i - 1]
            curr = series[i]
            if prev != 0:
                growth = (curr - prev) / abs(prev)
            else:
                growth = None
            growth_rates.append(growth)
        if len(series) > 1 and series[0] != 0:
            annualized = (series[-1] / series[0]) ** (1 / (len(series) - 1)) - 1
        else:
            annualized = None
    except Exception as e:
        return {"error": str(e)}
    return {"annualized_growth_rate": annualized, "period_growth_rates": growth_rates}
