"""Shared "one square per day, coloured by that day's flag level" logic
used by both the admin list (spec section 9) and the monthly summary
(spec section 10) -- kept in one place so the two screens can never
silently disagree about which level a given day gets coloured.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Flag
from app.domain.rules.types import FlagLevel


def level_rank(level: str) -> int:
    return list(FlagLevel).index(FlagLevel(level))


async def build_level_by_day(session: AsyncSession, patient_id, first: date, last: date) -> dict[int, str]:
    """Colours each day in [first, last] by the highest-level flag whose
    most recent event landed on it (a flag's `last_fired_at` advances
    every time a repeat firing adds an event to it -- domain/rules/flags.py).
    """
    flags = (await session.execute(select(Flag).where(Flag.patient_id == patient_id))).scalars().all()
    level_by_day: dict[int, str] = {}
    for f in flags:
        if first <= f.last_fired_at.date() <= last:
            day = f.last_fired_at.date().day
            existing = level_by_day.get(day)
            if existing is None or level_rank(f.level.value) > level_rank(existing):
                level_by_day[day] = f.level.value
    return level_by_day
