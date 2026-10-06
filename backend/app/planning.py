"""Goal planning math: the annual return needed to reach a target, plus a
short realism note.

Educational only — simple compound-growth calculations, not advice or
guarantees. The future value of a starting capital plus regular monthly
contributions is:

    FV(i) = C*(1+i)^n + M * ((1+i)^n - 1) / i

where C = current capital, M = monthly contribution, i = monthly rate,
n = number of months. There is no closed form for i when M > 0, so we solve
it numerically (bisection); with M = 0 it reduces to a closed form.
"""

from __future__ import annotations

import datetime


def required_annual_return(
    current: float, monthly: float, target: float, years: float
) -> float | None:
    """Annual return needed to reach `target`. Returns 0.0 if reachable with no
    growth, or None if effectively unreachable (even at an absurd rate)."""
    if years <= 0:
        return None
    n = years * 12.0

    def fv(i: float) -> float:
        if i == 0:
            return current + monthly * n
        return current * (1 + i) ** n + monthly * (((1 + i) ** n - 1) / i)

    if fv(0.0) >= target:
        return 0.0
    hi = 1.0  # 100% per month — an absurdly high upper bound
    if fv(hi) < target:
        return None

    lo = 0.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if fv(mid) < target:
            lo = mid
        else:
            hi = mid
    monthly_rate = (lo + hi) / 2
    return (1 + monthly_rate) ** 12 - 1


def assess(r: float | None) -> str:
    """A short, honest realism note for a required annual return."""
    if r is None:
        return (
            "Target effectively unreachable with these contributions. Raise "
            "contributions or extend the horizon."
        )
    if r <= 0:
        return "Already on track without investment growth."
    if r <= 0.04:
        return "Conservative: feasible with a low-risk allocation."
    if r <= 0.08:
        return "Moderate: in line with a diversified long-term portfolio."
    if r <= 0.12:
        return "Aggressive: high risk, not guaranteed."
    return (
        "Unrealistic: consider extending the horizon, raising contributions, "
        "or lowering the target."
    )


def compute_required_return(
    current: float, monthly: float, target: float, target_date: datetime.date
) -> dict:
    """Compute the required annual return for a dated target, with a note."""
    years = (target_date - datetime.date.today()).days / 365.25
    if years <= 0:
        return {
            "years": round(years, 2),
            "required_annual_return": None,
            "assessment": "The target date is in the past.",
        }
    r = required_annual_return(current, monthly, target, years)
    return {
        "years": round(years, 2),
        "required_annual_return": r,
        "assessment": assess(r),
    }
