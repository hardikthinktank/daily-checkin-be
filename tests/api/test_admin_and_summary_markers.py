"""T14 and T15: the two data-completeness markers on the admin list and
monthly summary.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db.models import CareAction, CareActionType, CallType, Flag


async def _add_checkin(session, patient_id, day: date, score=Decimal("3.0")):
    from app.db.models import CheckIn

    session.add(
        CheckIn(
            patient_id=patient_id,
            checkin_date=day,
            client_submission_id=str(uuid.uuid4()),
            fatigue=3,
            pain=3,
            swelling=3,
            today_score=score,
            is_current=True,
        )
    )


async def test_t14_fifteen_days_of_data_sixteen_day_marker_not_met(client, db_session, patient_on_biologic):
    first_of_month = date.today().replace(day=1)
    for i in range(15):
        day = first_of_month + timedelta(days=i)
        if day.month != first_of_month.month:
            break
        await _add_checkin(db_session, patient_on_biologic.id, day)
    await db_session.commit()

    resp = await client.get("/admin/patients", params={"month": first_of_month.isoformat()})
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["patient_id"] == str(patient_on_biologic.id))
    assert row["days_of_data_this_month"] == 15
    assert row["sixteen_day_marker_met"] is False
    assert row["sixteen_day_marker_short_by"] == 1


async def test_t14_sixteen_days_of_data_marker_met(client, db_session, patient_on_biologic):
    first_of_month = date.today().replace(day=1)
    for i in range(16):
        day = first_of_month + timedelta(days=i)
        if day.month != first_of_month.month:
            break
        await _add_checkin(db_session, patient_on_biologic.id, day)
    await db_session.commit()

    resp = await client.get("/admin/patients", params={"month": first_of_month.isoformat()})
    row = next(r for r in resp.json() if r["patient_id"] == str(patient_on_biologic.id))
    assert row["sixteen_day_marker_met"] is True
    assert row["sixteen_day_marker_short_by"] == 0


async def _make_flag(session, patient_id) -> uuid.UUID:
    flag = Flag(patient_id=patient_id, rule_code="D3-01", rule_version="1", level="Review", why_snapshot={})
    session.add(flag)
    await session.commit()
    await session.refresh(flag)
    return flag.id


async def test_t15_messages_only_no_call_live_call_marker_off(client, db_session, patient_on_biologic, human_actor):
    flag_id = await _make_flag(db_session, patient_on_biologic.id)
    db_session.add(
        CareAction(
            flag_id=flag_id,
            actor_id=human_actor.id,
            action_type=CareActionType.LOG_CALL,
            minutes=3,
            call_type=CallType.ASYNC_MESSAGE,
        )
    )
    # "however many" messages -- add a second one to make sure count doesn't matter
    db_session.add(
        CareAction(
            flag_id=flag_id,
            actor_id=human_actor.id,
            action_type=CareActionType.LOG_CALL,
            minutes=2,
            call_type=CallType.ASYNC_MESSAGE,
        )
    )
    await db_session.commit()

    month = date.today().replace(day=1)
    resp = await client.get(f"/patients/{patient_on_biologic.id}/monthly-summary", params={"month": month.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["record_facts"]["live_call_happened"] is False
    assert body["record_facts"]["minutes_recorded"] == 5  # minutes still counted even though it's not a "live call"

    admin_resp = await client.get("/admin/patients", params={"month": month.isoformat()})
    row = next(r for r in admin_resp.json() if r["patient_id"] == str(patient_on_biologic.id))
    assert row["live_call_this_month"] is False


async def test_t15_phone_call_turns_live_call_marker_on(client, db_session, patient_on_biologic, human_actor):
    flag_id = await _make_flag(db_session, patient_on_biologic.id)
    db_session.add(
        CareAction(
            flag_id=flag_id, actor_id=human_actor.id, action_type=CareActionType.LOG_CALL, minutes=10, call_type=CallType.PHONE
        )
    )
    await db_session.commit()

    month = date.today().replace(day=1)
    resp = await client.get(f"/patients/{patient_on_biologic.id}/monthly-summary", params={"month": month.isoformat()})
    assert resp.json()["record_facts"]["live_call_happened"] is True


async def test_last_checkin_level_correct_when_last_checkin_predates_the_viewed_month(
    client, db_session, patient_on_biologic
):
    """'Last check-in: date and level' (spec section 9) is a patient-level
    fact, not scoped to whichever month happens to be on screen. A bug
    here previously looked the level up in the WRONG month's data
    whenever the patient's true last check-in fell outside the month
    being viewed -- e.g. silently returning null, or matching an
    unrelated flag that happened to land on the same day-of-month number.
    """
    old_date = date.today().replace(day=1) - timedelta(days=45)  # a different month for sure
    old_datetime = datetime.combine(old_date, datetime.min.time(), tzinfo=timezone.utc)
    await _add_checkin(db_session, patient_on_biologic.id, old_date, score=Decimal("8.0"))
    db_session.add(
        Flag(
            patient_id=patient_on_biologic.id,
            rule_code="D3-01",
            rule_version="1",
            level="Urgent",
            why_snapshot={},
            first_fired_at=old_datetime,
            last_fired_at=old_datetime,
        )
    )
    await db_session.commit()

    current_month = date.today().replace(day=1)
    resp = await client.get("/admin/patients", params={"month": current_month.isoformat()})
    row = next(r for r in resp.json() if r["patient_id"] == str(patient_on_biologic.id))

    assert row["last_checkin_date"] == old_date.isoformat()
    assert row["last_checkin_level"] == "Urgent"
    # And the CURRENT month's own strip must not show any check-in days
    # at all -- the patient hasn't checked in this month.
    assert row["checkins_done"] == 0
