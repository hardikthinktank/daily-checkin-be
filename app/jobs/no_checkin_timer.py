"""R9: three days in a row with no check-in. This is the one rule that
"runs on a timer, not on a submission" (spec section 5) -- it has no
CheckinContext to react to, so it lives here instead of going through
app.domain.rules.engine.evaluate(). It still goes through the exact same
flags.reconcile() dedup path as every other rule, so a patient who stays
silent for weeks gets one flag with a growing event count, not a new one
every day.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import CheckIn, Patient, RuleDefinition
from app.domain.rules.flags import reconcile
from app.domain.rules.types import FlagLevel, RuleFiring
from app.services.context_builder import load_open_flags
from app.services.flag_apply import apply_intents

logger = logging.getLogger(__name__)

RULE_CODE = "D3-09"


async def _last_checkin_date(session: AsyncSession, patient_id) -> date | None:
    return await session.scalar(
        select(CheckIn.checkin_date)
        .where(CheckIn.patient_id == patient_id, CheckIn.is_current.is_(True))
        .order_by(CheckIn.checkin_date.desc())
        .limit(1)
    )


async def run_no_checkin_timer(session: AsyncSession, *, today: date | None = None) -> int:
    """Returns the number of patients for whom R9 fired (created or
    added an event). Safe to call daily -- see module docstring.
    """
    today = today or date.today()

    rule_row = await session.scalar(
        select(RuleDefinition).where(RuleDefinition.rule_code == RULE_CODE, RuleDefinition.is_active.is_(True))
    )
    if rule_row is None:
        logger.warning("D3-09 has no active RuleDefinition row; using built-in default of %s days", settings.no_checkin_streak_days)
        threshold_days = settings.no_checkin_streak_days
        rule_version = "builtin-default"
        level = FlagLevel.REVIEW
    else:
        threshold_days = rule_row.params.get("days", settings.no_checkin_streak_days)
        rule_version = str(rule_row.version)
        level = rule_row.level

    patients = (await session.execute(select(Patient))).scalars().all()
    now = datetime.now(timezone.utc)
    fired_count = 0

    for patient in patients:
        last_date = await _last_checkin_date(session, patient.id)
        reference_date = last_date or patient.enrollment_date
        days_since = (today - reference_date).days
        if days_since < threshold_days:
            continue

        firing = RuleFiring(
            rule_code=RULE_CODE,
            rule_version=rule_version,
            level=level,
            why={"days_since_last_checkin": days_since, "reference_date": reference_date.isoformat()},
            ask=(),
        )
        open_flags = await load_open_flags(session, patient.id)
        intents = reconcile([firing], open_flags, now)
        await apply_intents(session, patient.id, intents, now=now, checkin_id=None)
        fired_count += 1

    await session.commit()
    return fired_count


async def run_no_checkin_timer_standalone() -> int:
    """Entry point for the scheduler (app/jobs/scheduler.py) -- opens its
    own session since APScheduler jobs don't get one injected.
    """
    async with SessionLocal() as session:
        count = await run_no_checkin_timer(session)
        logger.info("no-checkin timer: R9 fired for %d patient(s)", count)
        return count
