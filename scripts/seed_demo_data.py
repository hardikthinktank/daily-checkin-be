"""Creates a handful of drugs, patients, and actors so the API can be
exercised end-to-end (Swagger UI included) without a frontend. Safe to
re-run -- looks up by natural key (name / mrn) before inserting.

    python -m scripts.seed_demo_data
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Actor, ActorRole, ActorType, Drug, Patient


async def _get_or_create_drug(session, name: str, is_biologic: bool) -> Drug:
    row = (await session.execute(select(Drug).where(Drug.name == name))).scalar_one_or_none()
    if row:
        return row
    row = Drug(name=name, is_biologic_or_similar=is_biologic)
    session.add(row)
    await session.flush()
    return row


async def _get_or_create_patient(session, mrn: str, name: str, diagnosis: str, drug: Drug, enrolled_days_ago: int) -> Patient:
    row = (await session.execute(select(Patient).where(Patient.mrn == mrn))).scalar_one_or_none()
    if row:
        return row
    row = Patient(
        mrn=mrn,
        name=name,
        diagnosis=diagnosis,
        current_drug_id=drug.id,
        enrollment_date=date.today() - timedelta(days=enrolled_days_ago),
    )
    session.add(row)
    await session.flush()
    return row


async def _get_or_create_actor(session, display_name: str, actor_type: ActorType, role: ActorRole) -> Actor:
    row = (
        await session.execute(select(Actor).where(Actor.display_name == display_name))
    ).scalar_one_or_none()
    if row:
        return row
    row = Actor(display_name=display_name, actor_type=actor_type, role=role)
    session.add(row)
    await session.flush()
    return row


async def seed_demo_data() -> None:
    async with SessionLocal() as session:
        biologic = await _get_or_create_drug(session, "Adalimumab (biologic)", True)
        conventional = await _get_or_create_drug(session, "Methotrexate", False)

        patients = [
            await _get_or_create_patient(
                session, "MRN-1001", "Jordan Ellis", "Rheumatoid arthritis", biologic, 400
            ),
            await _get_or_create_patient(
                session, "MRN-1002", "Priya Nair", "Rheumatoid arthritis", conventional, 200
            ),
        ]

        actors = [
            await _get_or_create_actor(session, "Care Manager (demo)", ActorType.HUMAN, ActorRole.CARE_MANAGER),
            await _get_or_create_actor(session, "Dr. Rao (demo physician)", ActorType.HUMAN, ActorRole.PHYSICIAN),
            await _get_or_create_actor(session, "Rule Engine (system)", ActorType.SYSTEM, ActorRole.SYSTEM),
        ]

        await session.commit()

        print("Drugs:")
        for d in (biologic, conventional):
            print(f"  {d.id}  {d.name}  biologic={d.is_biologic_or_similar}")
        print("Patients:")
        for p in patients:
            print(f"  {p.id}  {p.mrn}  {p.name}")
        print("Actors:")
        for a in actors:
            print(f"  {a.id}  {a.display_name}  type={a.actor_type.value}  role={a.role.value}")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
