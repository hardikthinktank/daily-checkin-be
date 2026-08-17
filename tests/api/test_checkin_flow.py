"""End-to-end HTTP flows exercising the full stack (rule engine + DB +
API), complementing the pure-engine T1-T12 tests in tests/domain/.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import CheckIn


async def test_same_day_resubmission_supersedes_but_keeps_history(client, db_session, patient_on_biologic):
    """Spec section 3: 'if the patient sends a second [check-in] the same
    day, it replaces the first, the rules run again, and the first
    version is kept in history rather than erased.' Distinct from T11
    (same client_submission_id resent) -- this is a genuinely new
    submission for the same (patient, date).
    """
    first = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 3, "pain": 3, "swelling": 3},
    )
    assert first.json()["version"] == 1
    assert first.json()["is_current"] is True
    first_id = first.json()["id"]

    second = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 7, "pain": 8, "swelling": 8},
    )
    assert second.json()["version"] == 2
    assert second.json()["is_current"] is True
    assert second.json()["id"] != first_id

    rows = (
        await db_session.execute(select(CheckIn).where(CheckIn.patient_id == patient_on_biologic.id))
    ).scalars().all()
    assert len(rows) == 2  # first version kept, not erased
    first_row = next(r for r in rows if str(r.id) == first_id)
    assert first_row.is_current is False
    second_row = next(r for r in rows if str(r.id) == second.json()["id"])
    assert second_row.supersedes_id == first_row.id


async def test_not_on_biologic_fever_never_asked_and_never_turns_critical(
    client, patient_not_on_biologic, seeded_rules
):
    resp = await client.post(
        f"/patients/{patient_not_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 5, "pain": 8, "swelling": 4},
    )
    body = resp.json()
    assert body["day_level"] == "Review"
    assert "fever" not in body["required_followups"]

    # Even if a client sends fever=yes anyway, it must not reach D3-06 or
    # the built-in failsafe for a non-biologic patient.
    followup = await client.post(
        f"/checkins/{body['id']}/followups",
        json={"fever": "yes", "days_at_level": "1", "new_joint": "no"},
    )
    assert followup.json()["day_level"] == "Review"


async def test_missing_required_field_is_rejected_with_uniform_error_shape(client, patient_on_biologic):
    resp = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": "x", "fatigue": 5, "pain": 8},  # swelling missing
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "validation_error"
    assert "detail" in body and "errors" in body["detail"]


async def test_out_of_range_answer_is_rejected(client, patient_on_biologic):
    resp = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": "x", "fatigue": 11, "pain": 8, "swelling": 4},
    )
    assert resp.status_code == 422


async def test_unknown_patient_returns_structured_404(client):
    resp = await client.post(
        f"/patients/{uuid.uuid4()}/checkins",
        json={"client_submission_id": "x", "fatigue": 5, "pain": 5, "swelling": 5},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "patient_not_found"


async def test_worklist_excludes_note_level_and_sorts_critical_first(client, db_session, patient_on_biologic, seeded_rules):
    # Seven quiet days (<=3.0) with nothing open -> R10 Note. Then a
    # separate high-pain submission -> R1 Review. Then a fever+biologic
    # submission -> R6 Critical. The Note must never show up in the
    # work list, and Critical must sort ahead of Review.
    from datetime import date, timedelta
    from decimal import Decimal

    from app.db.models import CheckIn

    for i in range(1, 7):
        db_session.add(
            CheckIn(
                patient_id=patient_on_biologic.id,
                checkin_date=date.today() - timedelta(days=i),
                client_submission_id=str(uuid.uuid4()),
                fatigue=3,
                pain=3,
                swelling=3,
                today_score=Decimal("3.0"),
                is_current=True,
            )
        )
    await db_session.commit()

    note_resp = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 3, "pain": 3, "swelling": 3},
    )
    assert note_resp.json()["day_level"] == "Note"

    worklist_after_note = await client.get("/care-manager/worklist")
    assert worklist_after_note.json() == []  # Note is recorded but is not work

    critical_resp = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 7, "pain": 8, "swelling": 8},
    )
    checkin_id = critical_resp.json()["id"]
    await client.post(f"/checkins/{checkin_id}/followups", json={"fever": "yes"})

    worklist = (await client.get("/care-manager/worklist")).json()
    assert worklist[0]["level"] == "Critical"
    assert all(f["level"] != "Note" for f in worklist)
