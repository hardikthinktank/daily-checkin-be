"""Drives spec section 11's test cases (T1-T15, T7 skipped -- see below)
against a LIVE server, asserting the documented expected result for each,
and prints PASS/FAIL. Companion to scripts/seed_test_case_fixtures.py,
which must be run first to build each patient's prior history.

    uvicorn app.main:app --reload &          # if not already running
    python -m scripts.seed_test_case_fixtures
    python -m scripts.run_test_cases

Patients/actors are looked up by name at run time (no hardcoded IDs), so
this works against any DB the fixtures script has seeded. Safe to re-run
same-day: a same-day resubmission just bumps the check-in's version (spec
section 3) instead of erroring. T9's flag-event-count check compares
before/after rather than a fixed number for the same reason -- each rerun
legitimately adds one more event to the still-open flag.

T7 (empty the rule table, confirm the built-in fever failsafe alone still
fires Critical) is not run here: doing it for real means deactivating
every row in the shared rule_definition table, which would blank out
rules for anything else hitting this same server. It's covered in
isolation by tests/domain/test_rules_engine.py::test_t7_....
"""
from __future__ import annotations

import sys
import uuid
from datetime import date

import httpx

BASE = "http://localhost:8000"
TODAY = date.today().isoformat()

client = httpx.Client(base_url=BASE, timeout=10)
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}: {detail}")


def patient_id(mrn: str) -> str:
    patients = client.get("/patients").json()
    row = next((p for p in patients if p["mrn"] == mrn), None)
    if row is None:
        raise SystemExit(f"Patient {mrn!r} not found -- run: python -m scripts.seed_test_case_fixtures")
    return row["id"]


def submit(pid: str, fatigue: int, pain: int, swelling: int, checkin_date: str = TODAY) -> dict:
    body = {
        "client_submission_id": f"trigger-{uuid.uuid4()}",
        "fatigue": fatigue, "pain": pain, "swelling": swelling, "checkin_date": checkin_date,
    }
    r = client.post(f"/patients/{pid}/checkins", json=body)
    r.raise_for_status()
    return r.json()


def followups(checkin_id: str, answers: dict) -> dict:
    r = client.post(f"/checkins/{checkin_id}/followups", json=answers)
    r.raise_for_status()
    return r.json()


def worklist_flag(pid: str, rule_code: str) -> dict | None:
    wl = client.get("/care-manager/worklist").json()
    return next((f for f in wl if f["patient_id"] == pid and f["rule_code"] == rule_code), None)


t1, t2, t3 = patient_id("TC-T1"), patient_id("TC-T2"), patient_id("TC-T3")
t4_t5, t6 = patient_id("TC-T4-T5"), patient_id("TC-T6")
t8, t9, t10, t12 = patient_id("TC-T8"), patient_id("TC-T9"), patient_id("TC-T10"), patient_id("TC-T12")
t13, t14, t15 = patient_id("TC-T13"), patient_id("TC-T14"), patient_id("TC-T15")

# T1: on drug, usual 3.0. Submit 3/3/3 -> no rules fire.
r = submit(t1, 3, 3, 3)
check("T1", r["day_level"] is None and r["required_followups"] == [], f"day_level={r['day_level']!r} required_followups={r['required_followups']}")

# T2: on drug, usual 3.0. Submit 5/8/4 -> Review, R1, fever asked.
r = submit(t2, 5, 8, 4)
check("T2", r["day_level"] == "Review" and "fever" in r["required_followups"], f"day_level={r['day_level']!r} required_followups={r['required_followups']}")

# T3: NOT on drug, usual 3.0. Submit 5/8/4 -> Review, fever NOT asked.
r = submit(t3, 5, 8, 4)
check("T3", r["day_level"] == "Review" and "fever" not in r["required_followups"], f"day_level={r['day_level']!r} required_followups={r['required_followups']}")

# T4: on drug, usual 3.0. Submit 7/8/8 -> Urgent (R1,R2,R4).
r4 = submit(t4_t5, 7, 8, 8)
check("T4", r4["day_level"] == "Urgent", f"day_level={r4['day_level']!r}")

# T5: continue T4, answer fever=yes -> Critical (R6 added).
r5 = followups(r4["id"], {"fever": "yes"})
check("T5", r5["day_level"] == "Critical", f"day_level={r5['day_level']!r}")

# T6: NOT on drug, same as T4. Submit 7/8/8 -> Urgent, then fever=yes -> unchanged.
r6a = submit(t6, 7, 8, 8)
r6b = followups(r6a["id"], {"fever": "yes"})
check("T6", r6a["day_level"] == "Urgent" and r6b["day_level"] == "Urgent", f"before={r6a['day_level']!r} after={r6b['day_level']!r}")

print("T7  SKIP: requires emptying the shared rule_definition table -- destructive to this dev DB. "
      "Already verified in isolation by tests/domain/test_rules_engine.py::test_t7_...")

# T8: on drug, only 3 days history. Submit 8/8/8 -> Review only (R1,R2), no R4.
r = submit(t8, 8, 8, 8)
check("T8", r["day_level"] == "Review", f"day_level={r['day_level']!r} (must NOT be Urgent -- no usual_score yet)")

# T9: on drug, pain flag already open. Submit 5/8/5 -> same flag gains exactly one more event.
before = worklist_flag(t9, "D3-01")
before_count = before["event_count"] if before else 0
before_id = before["id"] if before else None
submit(t9, 5, 8, 5)
after = worklist_flag(t9, "D3-01")
check(
    "T9",
    after is not None and after["id"] == before_id and after["event_count"] == before_count + 1,
    f"before_count={before_count} after_count={after['event_count'] if after else None} same_flag={after and after['id'] == before_id}",
)

# T10: on drug, fatigue 8 the two prior days. Submit 8/4/4 -> Review, R3 (asks sleep).
r = submit(t10, 8, 4, 4)
check("T10", r["day_level"] == "Review" and "sleep" in r["required_followups"], f"day_level={r['day_level']!r} required_followups={r['required_followups']}")

# T11: same submission sent twice (duplicate client_submission_id) -> one record, no new flags.
dup_id = f"t11-duplicate-{uuid.uuid4()}"
body = {"client_submission_id": dup_id, "fatigue": 4, "pain": 4, "swelling": 4, "checkin_date": "2026-08-16"}
r1 = client.post(f"/patients/{t1}/checkins", json=body).json()
r2 = client.post(f"/patients/{t1}/checkins", json=body).json()
check("T11", r1["created"] is True and r2["created"] is False and r1["id"] == r2["id"], f"first.created={r1['created']} second.created={r2['created']} same_id={r1['id']==r2['id']}")

# T12: on drug, 6 straight prior days <=3.0, nothing open. Submit 2/3/3 (7th day) -> Note (R10).
r = submit(t12, 2, 3, 3)
check("T12", r["day_level"] == "Note", f"day_level={r['day_level']!r}")

# T13: system actor tries to log a call -> 403, database rejects it.
system_actor = next(a for a in client.get("/actors").json() if a["actor_type"] == "system")
flag = worklist_flag(t13, "D3-02") or worklist_flag(t13, "D3-01")
body = {"actor_id": system_actor["id"], "minutes": 15, "call_type": "phone", "note": "test"}
resp = client.post(f"/flags/{flag['id']}/log-call", json=body)
check("T13", resp.status_code == 403, f"status={resp.status_code} body={resp.json()}")

# T14: 15 check-ins so far this month -> 16-day marker not met, short by 1.
row = next(r for r in client.get("/admin/patients", params={"month": TODAY[:8] + "01"}).json() if r["patient_id"] == t14)
check("T14", row["sixteen_day_marker_met"] is False and row["sixteen_day_marker_short_by"] == 1, f"days={row['days_of_data_this_month']} met={row['sixteen_day_marker_met']} short_by={row['sixteen_day_marker_short_by']}")

# T15: only an async message logged -> live-call marker off.
summary = client.get(f"/patients/{t15}/monthly-summary", params={"month": TODAY[:8] + "01"}).json()
check("T15", summary["record_facts"]["live_call_happened"] is False, f"record_facts={summary['record_facts']}")

print()
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} passed (T7 skipped by design)")
sys.exit(0 if passed == len(results) else 1)
