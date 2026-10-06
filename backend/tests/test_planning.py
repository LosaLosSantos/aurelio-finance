"""Pure-math unit tests for the goal-planning module (no DB needed)."""

from __future__ import annotations

import datetime

from app.planning import assess, compute_required_return, required_annual_return


def test_reachable_without_growth_returns_zero():
    # 10k + 100/mo for 10 years = 22k >= 20k target
    assert required_annual_return(10_000, 100, 20_000, 10) == 0.0


def test_unreachable_returns_none():
    assert required_annual_return(0, 0, 1_000_000, 5) is None


def test_invalid_horizon_returns_none():
    assert required_annual_return(1000, 100, 5000, 0) is None
    assert required_annual_return(1000, 100, 5000, -1) is None


def test_lump_sum_doubling_in_ten_years_is_about_7pct():
    # Rule of 72: doubling in 10y needs ~7.2%/yr
    r = required_annual_return(10_000, 0, 20_000, 10)
    assert r is not None and 0.069 < r < 0.075


def test_bisection_solution_actually_reaches_target():
    current, monthly, target, years = 5_000, 200, 60_000, 12
    r = required_annual_return(current, monthly, target, years)
    assert r is not None and r > 0
    i = (1 + r) ** (1 / 12) - 1  # back to a monthly rate
    n = years * 12
    fv = current * (1 + i) ** n + monthly * (((1 + i) ** n - 1) / i)
    assert abs(fv - target) / target < 0.001  # within 0.1%


def test_assess_bands():
    assert "unreachable" in assess(None).lower()
    assert "on track" in assess(0.0).lower()
    assert "conservative" in assess(0.03).lower()
    assert "moderate" in assess(0.06).lower()
    assert "aggressive" in assess(0.10).lower()
    assert "unrealistic" in assess(0.20).lower()


def test_compute_required_return_past_date():
    past = datetime.date.today() - datetime.timedelta(days=30)
    res = compute_required_return(1000, 100, 5000, past)
    assert res["required_annual_return"] is None
    assert "past" in res["assessment"].lower()
