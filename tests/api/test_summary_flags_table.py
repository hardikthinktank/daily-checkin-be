"""Spec section 10.6: the monthly summary's flags table needs "rule, what
fired it, level, first date, number of events, status, minutes" -- this
covers the "what fired it" column specifically (easy to silently drop
since it duplicates section 8's "why it fired" via a different path), and
the R9-without-a-rule-row edge case that used to crash this lookup.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.db.models import Flag


async def test_flags_table_includes_what_fired_it_description(client, db_session, patient_on_biologic, seeded_rules):
    resp = await client.post(
        f"/patients/{patient_on_biologic.id}/checkins",
        json={"client_submission_id": str(uuid.uuid4()), "fatigue": 3, "pain": 8, "swelling": 3},
    )
    assert resp.status_code == 201

    month = date.today().replace(day=1)
    summary = await client.get(f"/patients/{patient_on_biologic.id}/monthly-summary", params={"month": month.isoformat()})
    row = next(r for r in summary.json()["flags_table"] if r["rule_code"] == "D3-01")
    assert row["what_fired_it"] == "Pain is 7 or higher."


async def test_flag_detail_and_summary_do_not_crash_for_a_flag_with_no_matching_rule_row(
    client, db_session, patient_on_biologic
):
    """Reproduces the R9-without-an-active-rule-definition path
    (app/jobs/no_checkin_timer.py's "builtin-default" fallback): the flag
    exists but rule_version isn't a real DB version number. Both
    "why it fired" (section 8) and the summary's flags table (section
    10.6) must degrade gracefully, not 500.
    """
    flag = Flag(
        patient_id=patient_on_biologic.id,
        rule_code="D3-09",
        rule_version="builtin-default",
        level="Review",
        why_snapshot={"days_since_last_checkin": 5},
    )
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    detail = await client.get(f"/flags/{flag.id}")
    assert detail.status_code == 200
    assert "no matching rule_definition" in detail.json()["rule_description"]

    month = date.today().replace(day=1)
    summary = await client.get(f"/patients/{patient_on_biologic.id}/monthly-summary", params={"month": month.isoformat()})
    assert summary.status_code == 200
    row = next(r for r in summary.json()["flags_table"] if r["rule_code"] == "D3-09")
    assert "no matching rule_definition" in row["what_fired_it"]
