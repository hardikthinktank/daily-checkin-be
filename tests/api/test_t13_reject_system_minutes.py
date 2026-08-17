"""T13: only a human can add minutes. If the system itself tries to
write a minutes entry, the DATABASE must refuse it -- not the screen,
not the API layer. This test bypasses the API/service layer entirely and
inserts directly against the database with a system actor, to prove the
`reject_system_minutes` trigger (migration 0002) is the actual guarantee,
not just the app-layer check in flag_service.log_call.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import CareAction, CareActionType, CallType, Flag


async def _make_open_flag(session, patient_id) -> uuid.UUID:
    flag = Flag(
        patient_id=patient_id,
        rule_code="D3-01",
        rule_version="1",
        level="Review",
        why_snapshot={},
    )
    session.add(flag)
    await session.commit()
    await session.refresh(flag)
    return flag.id


async def test_t13_database_rejects_system_actor_logging_minutes(db_session, patient_on_biologic, system_actor):
    flag_id = await _make_open_flag(db_session, patient_on_biologic.id)

    db_session.add(
        CareAction(
            flag_id=flag_id,
            actor_id=system_actor.id,
            action_type=CareActionType.LOG_CALL,
            minutes=10,
            call_type=CallType.PHONE,
        )
    )
    with pytest.raises(IntegrityError, match="system actors may not record"):
        await db_session.commit()


async def test_t13_database_allows_human_actor_logging_minutes(db_session, patient_on_biologic, human_actor):
    flag_id = await _make_open_flag(db_session, patient_on_biologic.id)

    db_session.add(
        CareAction(
            flag_id=flag_id,
            actor_id=human_actor.id,
            action_type=CareActionType.LOG_CALL,
            minutes=10,
            call_type=CallType.PHONE,
        )
    )
    await db_session.commit()  # must not raise


async def test_t13_system_actor_still_rejected_via_the_api_layer(
    client, db_session, patient_on_biologic, system_actor
):
    """Defense in depth: the app-layer check in flag_service.log_call
    (403) is a nicety on top of the trigger, not a replacement for it --
    but it should still work.
    """
    flag_id = await _make_open_flag(db_session, patient_on_biologic.id)
    resp = await client.post(
        f"/flags/{flag_id}/log-call",
        json={"actor_id": str(system_actor.id), "minutes": 5, "call_type": "phone"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "system_actor_forbidden"
