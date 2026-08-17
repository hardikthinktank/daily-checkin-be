"""R9 (spec section 5): three days in a row with no check-in. Runs on a
timer, not a submission -- see app/jobs/no_checkin_timer.py. Not one of
the spec's T1-T15 (which are explicitly submission-driven), but it's a
real code path and needs its own coverage.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import CheckIn, Flag
from app.jobs.no_checkin_timer import run_no_checkin_timer


async def _add_checkin(session, patient_id, day: date):
    session.add(
        CheckIn(
            patient_id=patient_id,
            checkin_date=day,
            client_submission_id=str(uuid.uuid4()),
            fatigue=3,
            pain=3,
            swelling=3,
            today_score=Decimal("3.0"),
            is_current=True,
        )
    )
    await session.commit()


async def test_r9_does_not_fire_before_three_days_of_silence(db_session, patient_on_biologic, seeded_rules):
    await _add_checkin(db_session, patient_on_biologic.id, date.today() - timedelta(days=2))
    fired = await run_no_checkin_timer(db_session, today=date.today())
    assert fired == 0
    flag_count = await db_session.scalar(select(func.count(Flag.id)).where(Flag.patient_id == patient_on_biologic.id))
    assert flag_count == 0


async def test_r9_fires_review_flag_after_three_days_of_silence(db_session, patient_on_biologic, seeded_rules):
    await _add_checkin(db_session, patient_on_biologic.id, date.today() - timedelta(days=3))
    fired = await run_no_checkin_timer(db_session, today=date.today())
    assert fired == 1

    flag = await db_session.scalar(select(Flag).where(Flag.patient_id == patient_on_biologic.id))
    assert flag.rule_code == "D3-09"
    assert flag.level.value == "Review"
    assert flag.event_count == 1


async def test_r9_never_asked_and_a_new_patient_uses_enrollment_date_as_reference(db_session, patient_on_biologic, seeded_rules):
    # No check-ins at all -- patient_on_biologic fixture enrolls 400 days ago.
    fired = await run_no_checkin_timer(db_session, today=date.today())
    assert fired == 1
    flag = await db_session.scalar(select(Flag).where(Flag.patient_id == patient_on_biologic.id))
    assert flag.why_snapshot["days_since_last_checkin"] == 400


async def test_r9_repeated_runs_within_72h_add_events_not_new_flags(db_session, patient_on_biologic, seeded_rules):
    await _add_checkin(db_session, patient_on_biologic.id, date.today() - timedelta(days=4))

    await run_no_checkin_timer(db_session, today=date.today())
    await run_no_checkin_timer(db_session, today=date.today())
    await run_no_checkin_timer(db_session, today=date.today())

    flags = (await db_session.execute(select(Flag).where(Flag.patient_id == patient_on_biologic.id))).scalars().all()
    assert len(flags) == 1
    assert flags[0].event_count == 3


async def test_r9_falls_back_to_builtin_default_when_rule_row_missing(db_session, patient_on_biologic):
    # Deliberately no `seeded_rules` fixture -- rule_definition is empty,
    # same spirit as T7 for the submission path: the timer job must not
    # silently do nothing just because the DB row is missing.
    await _add_checkin(db_session, patient_on_biologic.id, date.today() - timedelta(days=5))
    fired = await run_no_checkin_timer(db_session, today=date.today())
    assert fired == 1
    flag = await db_session.scalar(select(Flag).where(Flag.patient_id == patient_on_biologic.id))
    assert flag.rule_version == "builtin-default"
