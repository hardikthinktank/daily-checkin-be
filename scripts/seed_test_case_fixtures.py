"""Builds the exact prior-history state each spec-section-11 test case
(T1-T15, minus T7/T11/T13 which need no special history) requires, using
the real checkin_service/flag_service code paths -- so the resulting DB
state is identical to what real traffic would produce. Patients are
looked up by a stable "TC-*" MRN and created if missing, so this is safe
to re-run.

    python -m scripts.seed_test_case_fixtures

Companion to scripts/run_test_cases.py, which drives these patients
through the live API and asserts the spec's expected result for each.

T1's history is deliberately NOT a flat run of 3/3/3 every day: 20
identical days at <=3.0 would also satisfy R10 ("seven check-ins in a
row at 3.0 or below with nothing open") and fire a Note flag -- which is
correct behaviour for R10 (it has its own dedicated test, T12), but not
what T1 is testing. One day is nudged to 4/4/4 to break that streak while
keeping the 14-day median at 3.0 (13x3.0 + 1x4.0 still medians to 3.0).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Actor, ActorRole, ActorType, CallType, Drug, Patient
from app.services import checkin_service, flag_service

TODAY = date.today()


async def get_or_create_patient(session, mrn, name, diagnosis, drug_id) -> Patient:
    row = (await session.execute(select(Patient).where(Patient.mrn == mrn))).scalar_one_or_none()
    if row:
        return row
    row = Patient(name=name, mrn=mrn, diagnosis=diagnosis, current_drug_id=drug_id, enrollment_date=TODAY - timedelta(days=60))
    session.add(row)
    await session.flush()
    return row


async def get_or_create_actor(session, display_name, actor_type, role) -> Actor:
    row = (await session.execute(select(Actor).where(Actor.display_name == display_name))).scalar_one_or_none()
    if row:
        return row
    row = Actor(display_name=display_name, actor_type=actor_type, role=role)
    session.add(row)
    await session.flush()
    return row


async def submit(session, patient_id, checkin_date, fatigue, pain, swelling, followups=None):
    result = await checkin_service.submit_checkin(
        session, patient_id, client_submission_id=str(uuid.uuid4()),
        fatigue=fatigue, pain=pain, swelling=swelling, checkin_date=checkin_date,
    )
    if followups:
        result = await checkin_service.submit_followups(session, result.checkin.id, followups)
    return result


async def baseline(session, patient_id, days, end_offset, fatigue=3, pain=3, swelling=3):
    """`days` consecutive check-ins of the same values, ending `end_offset`
    days before today (end_offset=1 means the most recent baseline day is
    yesterday)."""
    start = TODAY - timedelta(days=end_offset + days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        await submit(session, patient_id, d, fatigue, pain, swelling)


async def main():
    async with SessionLocal() as session:
        biologic = (await session.execute(select(Drug).where(Drug.name == "Adalimumab (biologic)"))).scalar_one()
        conventional = (await session.execute(select(Drug).where(Drug.name == "Methotrexate"))).scalar_one()
        human = await get_or_create_actor(session, "QA Payload Guide (human)", ActorType.HUMAN, ActorRole.CARE_MANAGER)
        await session.commit()

        # T1: on drug, usual score 3.0, 20 days of history, WITHOUT tripping R10.
        p = await get_or_create_patient(session, "TC-T1", "TC T1 Patient", "RA", biologic.id)
        await session.commit()
        start = TODAY - timedelta(days=20)
        for i in range(20):
            d = start + timedelta(days=i)
            v = 4 if d == TODAY - timedelta(days=6) else 3
            await submit(session, p.id, d, v, v, v)

        # T2: on drug, usual score 3.0.
        p = await get_or_create_patient(session, "TC-T2", "TC T2 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=1)

        # T3: NOT on drug, usual score 3.0.
        p = await get_or_create_patient(session, "TC-T3", "TC T3 Patient", "RA", conventional.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=1)

        # T4/T5: on drug, usual score 3.0.
        p = await get_or_create_patient(session, "TC-T4-T5", "TC T4 T5 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=1)

        # T6: NOT on drug, same as T4.
        p = await get_or_create_patient(session, "TC-T6", "TC T6 Patient", "RA", conventional.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=1)

        # T8: on drug, only 3 days of history (no usual_score yet).
        p = await get_or_create_patient(session, "TC-T8", "TC T8 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=3, end_offset=1)

        # T9: on drug, one prior R1 (pain) firing yesterday -> flag already open.
        p = await get_or_create_patient(session, "TC-T9", "TC T9 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=2)
        await submit(session, p.id, TODAY - timedelta(days=1), fatigue=5, pain=8, swelling=3)

        # T10: on drug, fatigue 8 on the two prior days.
        p = await get_or_create_patient(session, "TC-T10", "TC T10 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=14, end_offset=3)
        await submit(session, p.id, TODAY - timedelta(days=2), fatigue=8, pain=3, swelling=3)
        await submit(session, p.id, TODAY - timedelta(days=1), fatigue=8, pain=3, swelling=3)

        # T12: on drug, 6 straight prior days <=3.0, nothing open.
        p = await get_or_create_patient(session, "TC-T12", "TC T12 Patient", "RA", biologic.id)
        await session.commit()
        await baseline(session, p.id, days=6, end_offset=1, fatigue=2, pain=3, swelling=3)

        # T13: any patient with an open flag; the system actor to try (and fail) logging a call.
        p = await get_or_create_patient(session, "TC-T13", "TC T13 Patient", "RA", biologic.id)
        await session.commit()
        await submit(session, p.id, TODAY, fatigue=8, pain=8, swelling=8)

        # T14: check-ins for every day of the current month so far.
        p = await get_or_create_patient(session, "TC-T14", "TC T14 Patient", "RA", biologic.id)
        await session.commit()
        month_start = TODAY.replace(day=1)
        d = month_start
        while d <= TODAY:
            await submit(session, p.id, d, fatigue=3, pain=3, swelling=3)
            d += timedelta(days=1)

        # T15: a flag exists, only an async_message was logged against it (no phone/video).
        p = await get_or_create_patient(session, "TC-T15", "TC T15 Patient", "RA", biologic.id)
        await session.commit()
        await submit(session, p.id, TODAY, fatigue=5, pain=8, swelling=4)
        worklist = await flag_service.get_work_list(session)
        flag = next(f for f in worklist if f.patient_id == p.id)
        await flag_service.log_call(
            session, flag.id, human.id, minutes=10, call_type=CallType.ASYNC_MESSAGE,
            note="Messaged patient, no call needed.",
        )

        print("Fixtures ready. Run: python -m scripts.run_test_cases")


if __name__ == "__main__":
    asyncio.run(main())
