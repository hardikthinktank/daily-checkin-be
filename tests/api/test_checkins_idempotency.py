"""T11: the phone attaches a random ID to each submission. If it loses
signal and resends the same submission, the server must save it once --
exactly one record, no new flags on the replay.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.models import CheckIn, Flag


async def test_t11_duplicate_client_submission_id_creates_one_record_no_new_flags(
    client, db_session, patient_on_biologic, seeded_rules
):
    submission_id = str(uuid.uuid4())
    payload = {"client_submission_id": submission_id, "fatigue": 7, "pain": 8, "swelling": 8}

    first = await client.post(f"/patients/{patient_on_biologic.id}/checkins", json=payload)
    assert first.status_code == 201
    assert first.json()["created"] is True

    second = await client.post(f"/patients/{patient_on_biologic.id}/checkins", json=payload)
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]

    checkin_count = await db_session.scalar(
        select(func.count(CheckIn.id)).where(CheckIn.client_submission_id == submission_id)
    )
    assert checkin_count == 1

    flag_count = await db_session.scalar(select(func.count(Flag.id)).where(Flag.patient_id == patient_on_biologic.id))
    assert flag_count == 2  # R1 (pain>=7) + R2 (swelling>=7) -- created once, not duplicated


async def test_resending_followup_answers_does_not_duplicate_flags(
    client, db_session, patient_on_biologic, seeded_rules
):
    payload = {"client_submission_id": str(uuid.uuid4()), "fatigue": 7, "pain": 8, "swelling": 8}
    resp = await client.post(f"/patients/{patient_on_biologic.id}/checkins", json=payload)
    checkin_id = resp.json()["id"]

    followups = {"fever": "yes", "days_at_level": "1", "new_joint": "no", "which_joints": ["knees"], "morning_stiffness": "under 30 min"}
    r1 = await client.post(f"/checkins/{checkin_id}/followups", json=followups)
    assert r1.json()["day_level"] == "Critical"

    r2 = await client.post(f"/checkins/{checkin_id}/followups", json=followups)
    assert r2.json()["day_level"] == "Critical"

    critical_flags = await db_session.scalar(
        select(func.count(Flag.id)).where(Flag.patient_id == patient_on_biologic.id, Flag.rule_code == "D3-06")
    )
    assert critical_flags == 1
