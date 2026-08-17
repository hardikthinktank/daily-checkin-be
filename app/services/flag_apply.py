"""Turns domain.rules.flags.FlagIntent objects into actual Flag/FlagEvent
writes. Shared by the submission path (checkin_service) and the R9 timer
job (jobs/no_checkin_timer.py) so the two can never drift apart on how a
"create" vs "add_event" intent gets persisted.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Flag, FlagEvent
from app.domain.rules.flags import FlagIntent


async def apply_intents(
    session: AsyncSession,
    patient_id: uuid.UUID,
    intents: list[FlagIntent],
    *,
    now: datetime,
    checkin_id: uuid.UUID | None,
) -> None:
    for intent in intents:
        rule_version = str(intent.firing.rule_version)
        if intent.kind == "create":
            flag = Flag(
                patient_id=patient_id,
                rule_code=intent.firing.rule_code,
                rule_version=rule_version,
                level=intent.firing.level,
                first_fired_at=now,
                last_fired_at=now,
                event_count=1,
                why_snapshot=intent.firing.why,
            )
            session.add(flag)
            await session.flush()  # need flag.id for the FlagEvent FK
        else:  # add_event
            flag = await session.get(Flag, intent.existing_flag_id)
            flag.event_count += 1
            flag.last_fired_at = now
            flag.why_snapshot = intent.firing.why
            if intent.raise_to_level is not None:
                flag.level = intent.raise_to_level

        session.add(
            FlagEvent(
                flag_id=flag.id,
                checkin_id=checkin_id,
                rule_version=rule_version,
                fired_at=now,
                numbers_snapshot=intent.firing.why,
            )
        )
