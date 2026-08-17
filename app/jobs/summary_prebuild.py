"""Pre-builds the monthly summary cache (spec section 10: "the summary
should be built before the visit, not at the moment the physician
clicks"). Runs nightly for every patient's current month, and is also
invoked inline (via FastAPI BackgroundTasks) right after any write that
could change a summary -- see app/api/routers/checkins.py and
app/api/routers/care_manager.py.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import Patient
from app.services import summary_service

logger = logging.getLogger(__name__)


async def rebuild_current_month_for_patient(session: AsyncSession, patient_id) -> None:
    await summary_service.generate_and_cache(session, patient_id, date.today())


async def rebuild_all_patients_standalone() -> int:
    async with SessionLocal() as session:
        patient_ids = (await session.execute(select(Patient.id))).scalars().all()
        for patient_id in patient_ids:
            await summary_service.generate_and_cache(session, patient_id, date.today())
        logger.info("summary pre-build: refreshed %d patient(s)", len(patient_ids))
        return len(patient_ids)
