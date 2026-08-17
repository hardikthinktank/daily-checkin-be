"""Escalate/resolve, and the rule-administration versioning endpoint."""
from __future__ import annotations

import uuid

from app.db.models import Flag


async def _make_flag(db_session, patient_id) -> uuid.UUID:
    flag = Flag(patient_id=patient_id, rule_code="D3-01", rule_version="1", level="Review", why_snapshot={})
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)
    return flag.id


async def test_escalate_then_resolve_keeps_full_history(client, db_session, patient_on_biologic, human_actor):
    flag_id = await _make_flag(db_session, patient_on_biologic.id)

    esc = await client.post(
        f"/flags/{flag_id}/escalate", json={"actor_id": str(human_actor.id), "reason": "worsening pain"}
    )
    assert esc.status_code == 200
    assert esc.json()["action_type"] == "escalate"

    res = await client.post(
        f"/flags/{flag_id}/resolve", json={"actor_id": str(human_actor.id), "note": "physician reviewed, adjusted dose"}
    )
    assert res.status_code == 200

    detail = (await client.get(f"/flags/{flag_id}")).json()
    assert detail["status"] == "resolved"
    action_types = [a["action_type"] for a in detail["actions"]]
    assert action_types == ["escalate", "resolve"]  # nothing deleted, both kept in order


async def test_resolved_flag_rejects_further_acknowledge(client, db_session, patient_on_biologic, human_actor):
    flag_id = await _make_flag(db_session, patient_on_biologic.id)
    await client.post(f"/flags/{flag_id}/resolve", json={"actor_id": str(human_actor.id), "note": "done"})

    resp = await client.post(f"/flags/{flag_id}/acknowledge", json={"actor_id": str(human_actor.id)})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "flag_already_resolved"


async def test_rule_admin_new_version_closes_out_the_old_one(client):
    create1 = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-TEST",
            "level": "Review",
            "description": "Pain is 9 or higher.",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 9},
            "follow_up_questions": [],
            "care_manager_action": "Review within one business day.",
        },
    )
    assert create1.status_code == 200
    assert create1.json()["version"] == 1
    assert create1.json()["is_active"] is True

    create2 = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-TEST",
            "level": "Urgent",
            "description": "Pain is 8 or higher.",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 8},
            "follow_up_questions": [],
            "care_manager_action": "Call within 24 hours.",
        },
    )
    assert create2.status_code == 200
    assert create2.json()["version"] == 2

    active = (await client.get("/admin/rules", params={"active_only": True})).json()
    test_rules = [r for r in active if r["rule_code"] == "D3-TEST"]
    assert len(test_rules) == 1
    assert test_rules[0]["version"] == 2

    all_versions = (await client.get("/admin/rules", params={"active_only": False})).json()
    assert len([r for r in all_versions if r["rule_code"] == "D3-TEST"]) == 2


async def test_unknown_rule_type_is_rejected(client):
    resp = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-BOGUS",
            "level": "Note",
            "description": "x",
            "rule_type": "not_a_real_strategy",
            "params": {},
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "unknown_rule_type"


async def test_swagger_placeholder_params_rejected_and_does_not_close_out_the_working_version(client):
    """Reproduces the real incident: params={"additionalProp1": {}} (the
    generic Swagger UI placeholder for an empty dict) submitted for
    rule_type=threshold_gte, which needs {"field", "gte"}. Must be
    rejected with 422 -- and critically, must NOT deactivate whatever
    version of D3-01 was already live, since that's what actually broke
    every check-in submission in production.
    """
    working = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-INCIDENT",
            "level": "Review",
            "description": "Pain is 7 or higher.",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 7},
        },
    )
    assert working.status_code == 200

    broken = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-INCIDENT",
            "level": "Review",
            "description": "Pain is 7 or higher.",
            "rule_type": "threshold_gte",
            "params": {"additionalProp1": {}},
        },
    )
    assert broken.status_code == 422
    assert broken.json()["error_code"] == "invalid_rule_params"
    assert broken.json()["detail"]["missing"] == ["field", "gte"]

    active = (await client.get("/admin/rules", params={"active_only": True})).json()
    still_active = next(r for r in active if r["rule_code"] == "D3-INCIDENT")
    assert still_active["version"] == 1
    assert still_active["params"] == {"field": "pain", "gte": 7}


async def test_empty_rule_code_and_description_are_rejected(client):
    resp = await client.post(
        "/admin/rules",
        json={
            "rule_code": "",
            "level": "Review",
            "description": "",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 7},
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "validation_error"


async def test_unknown_followup_question_code_is_rejected(client):
    """A typo'd follow-up code (e.g. "fever_question" instead of "fever")
    would silently create a required follow-up the patient app has no
    matching field for and can never answer -- same failure shape as the
    params incident, just one layer over.
    """
    resp = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-TYPO",
            "level": "Review",
            "description": "Pain is 7 or higher.",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 7},
            "follow_up_questions": ["fever_question"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "validation_error"
    assert "unknown follow-up question code" in str(resp.json()["detail"])


async def test_known_followup_question_codes_are_accepted(client):
    resp = await client.post(
        "/admin/rules",
        json={
            "rule_code": "D3-KNOWN",
            "level": "Review",
            "description": "Pain is 7 or higher.",
            "rule_type": "threshold_gte",
            "params": {"field": "pain", "gte": 7},
            "follow_up_questions": ["days_at_level", "new_joint", "fever"],
        },
    )
    assert resp.status_code == 200
