import pytest

from tearsheet.analysis.growth import calculate_growth_rates


def test_sign_change_cagr_is_none_with_note():
    g = calculate_growth_rates([-50, 100])
    # Old code computed (-2) ** 1 - 1 here and complex numbers for longer series.
    assert g.cagr is None and "undefined" in g.notes[0]
    g = calculate_growth_rates([-0.5, 1.0, 2.0, 4.0])
    assert g.cagr is None and not isinstance(g.cagr, complex)


def test_cagr_annualizes_with_periods_per_year():
    assert calculate_growth_rates([100, 121]).cagr == pytest.approx(0.21)
    assert calculate_growth_rates([100, 110, 121]).cagr == pytest.approx(0.10)
    # Four quarters of 2% growth is ~8.24% a year.
    q = calculate_growth_rates([100, 102, 104.04, 106.1208, 108.243216], 4)
    assert q.cagr == pytest.approx(1.02**4 - 1)


def test_period_growth_uses_abs_prev_and_none_for_zero():
    g = calculate_growth_rates([0, 10, -10, -5])
    assert g.period_growth_rates == [None, -2.0, 0.5]
    assert any("previous value is 0" in n for n in g.notes)
    assert g.cagr is None
