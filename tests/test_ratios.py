import pytest

from tearsheet.analysis import ratios as r


def test_fcf_subtracts_absolute_capex():
    out = r.free_cash_flow(
        {"operating_cash_flow": 500.0, "capital_expenditure": -100.0}
    )
    assert out.value == 400.0
    # A source reporting capex as positive gives the same answer.
    out = r.free_cash_flow({"operating_cash_flow": 500.0, "capital_expenditure": 100.0})
    assert out.value == 400.0


def test_fcf_cross_checks_reported_value():
    out = r.free_cash_flow(
        {
            "operating_cash_flow": 500.0,
            "capital_expenditure": -100.0,
            "free_cash_flow": 350.0,
        }
    )
    assert out.value == 400.0 and "differs from reported" in out.notes[0]


def test_fcf_falls_back_to_reported_without_capex():
    out = r.free_cash_flow({"operating_cash_flow": 500.0, "free_cash_flow": 480.0})
    assert out.value == 480.0 and out.notes


def test_debt_to_equity_uses_total_debt_not_liabilities():
    f = {
        "total_debt": 800.0,
        "total_liabilities": 3000.0,
        "stockholders_equity": 2000.0,
    }
    assert r.STATEMENT_METRICS["debt_to_equity"](f).value == 0.4
    assert r.STATEMENT_METRICS["liabilities_to_equity"](f).value == 1.5


def test_pe_none_for_non_positive_eps():
    for eps in (-1.5, 0.0):
        out = r.pe_ratio(40.0, eps)
        assert out.value is None and "EPS <= 0" in out.notes[0]
    assert r.pe_ratio(40.0, 2.0).value == 20.0


def test_pb_none_for_negative_book_value():
    out = r.pb_ratio(40.0, {"stockholders_equity": -10.0, "shares_outstanding": 5.0})
    assert out.value is None and out.notes


def test_quick_ratio_missing_inventory_treated_as_zero():
    out = r.quick_ratio({"current_assets": 150.0, "current_liabilities": 100.0})
    assert out.value == 1.5 and "treated as 0" in out.notes[0]
    out = r.quick_ratio(
        {"current_assets": 150.0, "inventory": 50.0, "current_liabilities": 100.0}
    )
    assert out.value == 1.0 and not out.notes


def test_gross_margin_fallback_and_ebitda_fallback():
    out = r.gross_margin({"revenue": 200.0, "cost_of_revenue": 50.0})
    assert out.value == 0.75 and out.notes
    out = r.ebitda({"operating_income": 100.0, "depreciation_and_amortization": 20.0})
    assert out.value == 120.0 and out.notes


def test_zero_denominator_is_none():
    assert (
        r.STATEMENT_METRICS["net_margin"]({"net_income": 1.0, "revenue": 0.0}).value
        is None
    )


def test_dividend_yield():
    assert r.dividend_yield(50.0, 1.0).value == 0.02


def test_ttm_eps():
    periods = [("q4", {"diluted_eps": 1.0}), ("q3", {"diluted_eps": 0.5})] * 2
    assert r.ttm_eps(periods, "quarterly")[0] == 3.0
    assert r.ttm_eps(periods[:3], "quarterly")[0] is None
    assert r.ttm_eps(periods, "annual") == (1.0, None)


def _market(**kw):
    base = dict(
        price=40.0, eps=2.0, eps_note=None, ttm_dividends=1.0, currency_mismatch=None
    )
    return r.MarketInputs(**{**base, **kw})


def test_market_metrics_fill_latest_period_only():
    periods = [
        ("2025", {"stockholders_equity": 2000.0, "shares_outstanding": 100.0}),
        ("2024", {"stockholders_equity": 1500.0, "shares_outstanding": 100.0}),
    ]
    t = r.compute_fundamentals(
        periods, ["pe_ratio", "pb_ratio", "dividend_yield"], _market()
    )
    latest, older = t.periods[0][1], t.periods[1][1]
    assert latest == {"pe_ratio": 20.0, "pb_ratio": 2.0, "dividend_yield": 0.025}
    assert older == {"pe_ratio": None, "pb_ratio": None, "dividend_yield": None}


def test_currency_mismatch_skips_pe_pb():
    periods = [("2025", {"stockholders_equity": 2000.0, "shares_outstanding": 100.0})]
    t = r.compute_fundamentals(
        periods, ["pe_ratio", "pb_ratio"], _market(currency_mismatch="TWD vs USD")
    )
    assert t.periods[0][1] == {"pe_ratio": None, "pb_ratio": None}
    assert t.notes == ["TWD vs USD"]


def test_null_metric_gets_missing_input_note():
    t = r.compute_fundamentals([("2025", {"revenue": 100.0})], ["gross_margin"], None)
    assert t.periods[0][1]["gross_margin"] is None
    assert t.notes == ["gross_margin: null because cost_of_revenue not reported."]


@pytest.mark.parametrize("name", r.ALL_METRICS)
def test_every_metric_handles_empty_fields(name):
    t = r.compute_fundamentals([("2025", {})], [name], _market(price=None, eps=None))
    assert t.periods[0][1][name] is None
