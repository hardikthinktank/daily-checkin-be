"""The admin list (spec section 9): one row per patient, no drilling
required to see who needs attention.

The 16-day marker and live-call marker are facts about the record, shown
so operations can see where things stand. They are NOT a billing
decision and this module must never compute or expose anything that
looks like one -- see spec section 9's callout and section 12 ("time and
organisation").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CallType, CareAction, CareActionType, CheckIn, Flag, FlagStatus, Patient
from app.services.date_utils import month_bounds
from app.services.month_strip import build_level_by_day

SIXTEEN_DAY_MARKER_THRESHOLD = 16


@dataclass
class DayCell:
    day: int
    level: str | None  # None -> blank, no check-in that day


@dataclass
class AdminListRow:
    patient: Patient
    month_strip: list[DayCell]
    checkins_done: int
    checkins_expected: int
    checkins_pct: float
    average_score: float | None
    last_checkin_date: date | None
    last_checkin_level: str | None
    open_items: int
    minutes_this_month: int
    live_call_this_month: bool
    days_of_data_this_month: int
    sixteen_day_marker_met: bool
    sixteen_day_marker_short_by: int


async def _row_for_patient(session: AsyncSession, patient: Patient, month: date) -> AdminListRow:
    first, last, days_in_month = month_bounds(month)

    checkins = (
        await session.execute(
            select(CheckIn)
            .where(
                CheckIn.patient_id == patient.id,
                CheckIn.is_current.is_(True),
                CheckIn.checkin_date >= first,
                CheckIn.checkin_date <= last,
            )
            .order_by(CheckIn.checkin_date)
        )
    ).scalars().all()

    by_day: dict[int, CheckIn] = {c.checkin_date.day: c for c in checkins}
    level_by_day = await build_level_by_day(session, patient.id, first, last)

    month_strip = [
        DayCell(day=d, level=level_by_day.get(d) if d in by_day else None)
        for d in range(1, days_in_month + 1)
    ]

    scores = [c.today_score for c in checkins]
    average_score = float(sum(scores) / len(scores)) if scores else None

    last_checkin = (
        await session.execute(
            select(CheckIn)
            .where(CheckIn.patient_id == patient.id, CheckIn.is_current.is_(True))
            .order_by(CheckIn.checkin_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_level = None
    if last_checkin is not None:
        if first <= last_checkin.checkin_date <= last:
            # Falls inside the viewed month -- level_by_day already covers it.
            last_level = level_by_day.get(last_checkin.checkin_date.day)
        else:
            # The patient's true last check-in predates (or postdates) the
            # month being viewed -- look its level up on its own date
            # rather than misreading an unrelated same-numbered day in
            # the viewed month.
            other_month_levels = await build_level_by_day(
                session, patient.id, last_checkin.checkin_date, last_checkin.checkin_date
            )
            last_level = other_month_levels.get(last_checkin.checkin_date.day)

    open_items = await session.scalar(
        select(func.count(Flag.id)).where(
            Flag.patient_id == patient.id, Flag.status != FlagStatus.RESOLVED
        )
    )

    next_month_start = last + timedelta(days=1)
    care_actions = (
        await session.execute(
            select(CareAction)
            .join(Flag, Flag.id == CareAction.flag_id)
            .where(
                Flag.patient_id == patient.id,
                CareAction.created_at >= first,
                CareAction.created_at < next_month_start,
            )
        )
    ).scalars().all()
    minutes_this_month = sum(a.minutes or 0 for a in care_actions if a.action_type == CareActionType.LOG_CALL)
    live_call_this_month = any(
        a.action_type == CareActionType.LOG_CALL and a.call_type in (CallType.PHONE, CallType.VIDEO)
        for a in care_actions
    )

    days_of_data = len(checkins)
    short_by = max(0, SIXTEEN_DAY_MARKER_THRESHOLD - days_of_data)

    return AdminListRow(
        patient=patient,
        month_strip=month_strip,
        checkins_done=days_of_data,
        checkins_expected=days_in_month,
        checkins_pct=round(100 * days_of_data / days_in_month, 1),
        average_score=round(average_score, 1) if average_score is not None else None,
        last_checkin_date=last_checkin.checkin_date if last_checkin else None,
        last_checkin_level=last_level,
        open_items=open_items,
        minutes_this_month=minutes_this_month,
        live_call_this_month=live_call_this_month,
        days_of_data_this_month=days_of_data,
        sixteen_day_marker_met=short_by == 0,
        sixteen_day_marker_short_by=short_by,
    )


async def get_admin_list(session: AsyncSession, month: date) -> list[AdminListRow]:
    patients = (await session.execute(select(Patient).order_by(Patient.name))).scalars().all()
    return [await _row_for_patient(session, p, month) for p in patients]
