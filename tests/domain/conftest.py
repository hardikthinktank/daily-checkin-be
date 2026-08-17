"""Shared builders for hand-constructing rule-engine contexts in tests,
with no database involved -- matches spec section 11's requirement that
the engine be testable "on its own, with no screens and no database."
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain.rules.types import CheckinContext, DailyRecord, PatientHistory
from app.domain.scoring import score_change, today_score, usual_score

TODAY = date(2026, 8, 14)


def make_record(checkin_date: date, fatigue: int, pain: int, swelling: int, **follow_ups) -> DailyRecord:
    return DailyRecord(
        checkin_date=checkin_date,
        fatigue=fatigue,
        pain=pain,
        swelling=swelling,
        today_score=today_score(fatigue, pain, swelling),
        follow_up_answers=follow_ups,
    )


def make_context(
    fatigue: int,
    pain: int,
    swelling: int,
    *,
    checkin_date: date = TODAY,
    on_biologic: bool = True,
    prior_scores: list[Decimal] | None = None,
    recent_records: tuple[DailyRecord, ...] = (),
    open_flag_levels=frozenset(),
    follow_up_answers: dict[str, str] | None = None,
) -> CheckinContext:
    """Build one day's CheckinContext.

    `prior_scores` drives the usual-score/change calculation (most-recent
    first, matching scoring.usual_score's contract). `recent_records`
    drives streak rules (R3, R10) and must be supplied separately since
    streak rules need full daily records, not just scores.
    """
    today = make_record(checkin_date, fatigue, pain, swelling, **(follow_up_answers or {}))
    usual = usual_score(prior_scores) if prior_scores is not None else None
    change = score_change(today.today_score, usual)
    history = PatientHistory(
        on_biologic=on_biologic,
        open_flag_levels=frozenset(open_flag_levels),
        recent_records=recent_records,
    )
    return CheckinContext(today=today, usual_score=usual, change=change, history=history)


def consecutive_days_before(anchor: date, n: int) -> list[date]:
    """n dates immediately before `anchor`, most-recent-first."""
    return [anchor - timedelta(days=i) for i in range(1, n + 1)]


@pytest.fixture
def today():
    return TODAY
