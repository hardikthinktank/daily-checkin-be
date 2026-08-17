"""The monthly summary for the physician (spec section 10). Built to be
pre-computed, not built at click time -- generate_and_cache() is what the
background jobs (app/jobs/summary_prebuild.py) and the write paths
(new check-in, new flag/event, new care action) call; the read endpoint
should almost always be a cache hit, which is what gets it under the
spec's five-second target.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CareAction, CareActionType, CallType, CheckIn, Flag, MonthlySummaryCache, Patient
from app.services.admin_list_service import SIXTEEN_DAY_MARKER_THRESHOLD
from app.services.date_utils import month_bounds
from app.services.errors import PatientNotFoundError
from app.services.month_strip import build_level_by_day
from app.services.rule_descriptions import describe_rule


async def _load_patient(session: AsyncSession, patient_id: uuid.UUID) -> Patient:
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise PatientNotFoundError(detail={"patient_id": str(patient_id)})
    return patient


async def _build_payload(session: AsyncSession, patient: Patient, month: date) -> dict:
    first, last, days_in_month = month_bounds(month)
    next_month_start = last + timedelta(days=1)

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

    # section 2: symptom chart + section 3: score chart
    symptom_series = [
        {
            "date": c.checkin_date.isoformat(),
            "fatigue": c.fatigue,
            "pain": c.pain,
            "swelling": c.swelling,
        }
        for c in checkins
    ]
    score_series = [
        {
            "date": c.checkin_date.isoformat(),
            "today_score": float(c.today_score),
            "usual_score": float(c.usual_score) if c.usual_score is not None else None,
        }
        for c in checkins
    ]
    # A single "usual score" line for the whole chart, per spec ("a
    # dashed line at the patient's usual score") -- most recent usual
    # score in the month, since usual score drifts day to day.
    latest_usual = next((c.usual_score for c in reversed(checkins) if c.usual_score is not None), None)
    usual_score_line = float(latest_usual) if latest_usual is not None else None
    usual_plus_3_line = usual_score_line + 3.0 if usual_score_line is not None else None

    flags = (
        await session.execute(select(Flag).where(Flag.patient_id == patient.id))
    ).scalars().all()

    # section 5: month strip -- shared with the admin list so the two
    # screens can never disagree about a day's colour.
    level_by_day = await build_level_by_day(session, patient.id, first, last)
    checkin_days = {c.checkin_date.day for c in checkins}
    month_strip = [
        {"day": d, "level": level_by_day.get(d) if d in checkin_days else None}
        for d in range(1, days_in_month + 1)
    ]

    # section 4: days by level (bars) -- one bucket per day that had a
    # check-in, keyed by that day's colour (None = no rule fired).
    days_by_level = {"none": 0, "Note": 0, "Review": 0, "Urgent": 0, "Critical": 0}
    for d in checkin_days:
        level = level_by_day.get(d)
        days_by_level["none" if level is None else level] += 1

    # section 6: flags table -- every flag touching this patient whose
    # first-fired date falls in the month (a flag opened earlier that is
    # still open is not re-listed every month it stays open).
    flags_table = []
    for f in flags:
        if not (first <= f.first_fired_at.date() <= last):
            continue
        minutes = sum(
            a.minutes or 0
            for a in f.actions
            if a.action_type == CareActionType.LOG_CALL and first <= a.created_at.date() <= last
        )
        description, _ = await describe_rule(session, f.rule_code, f.rule_version)
        flags_table.append(
            {
                "rule_code": f.rule_code,
                "rule_version": f.rule_version,
                "what_fired_it": description,
                "level": f.level.value,
                "first_fired_at": f.first_fired_at.isoformat(),
                "event_count": f.event_count,
                "status": f.status.value,
                "minutes": minutes,
            }
        )

    # section 7: what the team did, in date order
    actions = (
        await session.execute(
            select(CareAction)
            .join(Flag, Flag.id == CareAction.flag_id)
            .where(
                Flag.patient_id == patient.id,
                CareAction.created_at >= first,
                CareAction.created_at < next_month_start,
            )
            .order_by(CareAction.created_at)
        )
    ).scalars().all()
    team_actions = [
        {
            "date": a.created_at.isoformat(),
            "action_type": a.action_type.value,
            "minutes": a.minutes,
            "call_type": a.call_type.value if a.call_type else None,
            "reason": a.reason,
            "note": a.note,
        }
        for a in actions
    ]

    # section 8: record facts
    days_of_data = len(checkins)
    live_call = any(
        a.action_type == CareActionType.LOG_CALL and a.call_type in (CallType.PHONE, CallType.VIDEO)
        for a in actions
    )
    total_minutes = sum(a.minutes or 0 for a in actions if a.action_type == CareActionType.LOG_CALL)

    return {
        "header": {
            "patient_id": str(patient.id),
            "patient_name": patient.name,
            "month": first.isoformat(),
            "drug": patient.current_drug.name,
            "days_reported": days_of_data,
            "days_in_month": days_in_month,
        },
        "symptom_chart": symptom_series,
        "score_chart": {
            "series": score_series,
            "usual_score_line": usual_score_line,
            "usual_plus_3_line": usual_plus_3_line,
        },
        "days_by_level": days_by_level,
        "month_strip": month_strip,
        "flags_table": flags_table,
        "team_actions": team_actions,
        "record_facts": {
            "days_of_data": days_of_data,
            "sixteen_day_marker_met": days_of_data >= SIXTEEN_DAY_MARKER_THRESHOLD,
            "sixteen_day_marker_short_by": max(0, SIXTEEN_DAY_MARKER_THRESHOLD - days_of_data),
            "live_call_happened": live_call,
            "minutes_recorded": total_minutes,
        },
    }


async def generate_and_cache(session: AsyncSession, patient_id: uuid.UUID, month: date) -> dict:
    patient = await _load_patient(session, patient_id)
    first, _, _ = month_bounds(month)
    payload = await _build_payload(session, patient, first)

    cache_row = await session.get(MonthlySummaryCache, (patient_id, first))
    if cache_row is None:
        cache_row = MonthlySummaryCache(patient_id=patient_id, month=first, payload=payload)
        session.add(cache_row)
    else:
        cache_row.payload = payload
    await session.commit()
    return payload


async def get_summary(session: AsyncSession, patient_id: uuid.UUID, month: date) -> dict:
    """Cache-first read (spec: built before the visit, target under five
    seconds). Falls back to a synchronous build on a cache miss so the
    endpoint is still correct the first time it's ever called for a
    given patient/month, just not as fast.
    """
    first, _, _ = month_bounds(month)
    cache_row = await session.get(MonthlySummaryCache, (patient_id, first))
    if cache_row is not None:
        return cache_row.payload
    return await generate_and_cache(session, patient_id, month)
