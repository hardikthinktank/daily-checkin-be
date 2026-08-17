"""API-level test fixtures. Runs against a REAL Postgres test database
(not sqlite, not mocks) -- required for T13, which tests an actual
database trigger, and generally in keeping with "test what you ship."

IMPORTANT: the CHECKIN_DATABASE_URL override below must happen before
anything imports app.config / app.db.base, since both read the setting
at import time.
"""
from __future__ import annotations

import os

os.environ["CHECKIN_DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/care_management_test"

import uuid
from datetime import date

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import Base, SessionLocal, engine
from app.db.models import Actor, ActorRole, ActorType, Drug, Patient, RuleDefinition
from app.domain.rules.seed_data import RULES
from app.main import app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _check_schema_exists():
    """The 0001/0002 Alembic migrations must already have been applied to
    care_management_test (see project README) -- this fixture just turns
    "forgot to migrate the test DB" into one clear error instead of a
    wall of unrelated failures.
    """
    async with SessionLocal() as session:
        try:
            await session.execute(text("SELECT 1 FROM patient LIMIT 1"))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "care_management_test has no schema. Run: "
                "CHECKIN_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/care_management_test "
                "alembic upgrade head"
            ) from e
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    """Truncates every app table before each test so tests are
    order-independent and never see another test's data.
    """
    async with engine.begin() as conn:
        table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_rules(db_session):
    for rule in RULES:
        db_session.add(
            RuleDefinition(
                rule_code=rule.rule_code,
                version=rule.version,
                level=rule.level.value,
                description=rule.description,
                rule_type=rule.rule_type,
                params=rule.params,
                follow_up_questions=list(rule.follow_up_questions),
                requires_fever_gate=rule.requires_fever_gate,
                care_manager_action=rule.care_manager_action,
                is_active=True,
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def biologic_drug(db_session) -> Drug:
    drug = Drug(name=f"Biologic-{uuid.uuid4().hex[:8]}", is_biologic_or_similar=True)
    db_session.add(drug)
    await db_session.commit()
    await db_session.refresh(drug)
    return drug


@pytest_asyncio.fixture
async def conventional_drug(db_session) -> Drug:
    drug = Drug(name=f"Conventional-{uuid.uuid4().hex[:8]}", is_biologic_or_similar=False)
    db_session.add(drug)
    await db_session.commit()
    await db_session.refresh(drug)
    return drug


async def make_patient(session, drug: Drug, *, name: str = "Test Patient", enrolled_days_ago: int = 400) -> Patient:
    from datetime import timedelta

    patient = Patient(
        name=name,
        mrn=f"MRN-{uuid.uuid4().hex[:10]}",
        diagnosis="Rheumatoid arthritis",
        current_drug_id=drug.id,
        enrollment_date=date.today() - timedelta(days=enrolled_days_ago),
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


@pytest_asyncio.fixture
async def patient_on_biologic(db_session, biologic_drug) -> Patient:
    return await make_patient(db_session, biologic_drug)


@pytest_asyncio.fixture
async def patient_not_on_biologic(db_session, conventional_drug) -> Patient:
    return await make_patient(db_session, conventional_drug)


@pytest_asyncio.fixture
async def human_actor(db_session) -> Actor:
    actor = Actor(display_name="Test Care Manager", actor_type=ActorType.HUMAN, role=ActorRole.CARE_MANAGER)
    db_session.add(actor)
    await db_session.commit()
    await db_session.refresh(actor)
    return actor


@pytest_asyncio.fixture
async def system_actor(db_session) -> Actor:
    actor = Actor(display_name="Test System", actor_type=ActorType.SYSTEM, role=ActorRole.SYSTEM)
    db_session.add(actor)
    await db_session.commit()
    await db_session.refresh(actor)
    return actor
