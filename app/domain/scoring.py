"""The D3 score and the usual-score comparison (spec section 4).

Deliberately not RAPID3, DAS28, or CDAI -- those are established clinical
measures with specific published formulas, two of which require a doctor
to count swollen joints in person. This score is patient-reported only.
Never rename this to imply otherwise; see tests/domain/test_naming.py.
"""
from __future__ import annotations

import statistics
from decimal import ROUND_HALF_UP, Decimal

MIN_PRIOR_CHECKINS_FOR_USUAL_SCORE = 5
USUAL_SCORE_WINDOW = 14


def today_score(fatigue: int, pain: int, swelling: int) -> Decimal:
    """(fatigue + pain + swelling) / 3, rounded to one decimal place."""
    raw = Decimal(fatigue + pain + swelling) / Decimal(3)
    return raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def usual_score(prior_scores: list[Decimal]) -> Decimal | None:
    """Median of the patient's last 14 reported scores.

    `prior_scores` must be ordered most-recent-first and must NOT include
    today's own score. Returns None when the patient has fewer than 5
    prior check-ins -- callers must not let any change-dependent rule fire
    in that case (a brand-new patient must not be told they are flaring
    on day three).
    """
    if len(prior_scores) < MIN_PRIOR_CHECKINS_FOR_USUAL_SCORE:
        return None
    window = prior_scores[:USUAL_SCORE_WINDOW]
    return Decimal(str(statistics.median(window))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def score_change(today: Decimal, usual: Decimal | None) -> Decimal | None:
    if usual is None:
        return None
    return today - usual
