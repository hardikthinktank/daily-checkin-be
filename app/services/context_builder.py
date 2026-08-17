"""Translates ORM rows into the plain dataclasses the domain layer
consumes. This is the ONLY place that boundary crossing happens -- see
module docstrings in app/domain/rules/types.py for why the split exists.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CheckIn, Flag, FlagStatus, Patient, RuleDefinition as RuleDefinitionRow
from app.domain.rules.flags import OpenFlagView
from app.domain.rules.types import (
    CheckinContext,
    DailyRecord,
    FlagLevel,
    PatientHistory,
    RuleDefinition,
)
from app.domain.scoring import score_change, usual_score

HISTORY_WINDOW = 14
OPEN_STATUSES = (FlagStatus.OPEN, FlagStatus.ACKNOWLEDGED, FlagStatus.ESCALATED)


def _to_daily_record(row: CheckIn) -> DailyRecord:
    return DailyRecord(
        checkin_date=row.checkin_date,
        fatigue=row.fatigue,
        pain=row.pain,
        swelling=row.swelling,
        today_score=row.today_score,
        follow_up_answers=row.follow_up_answers or {},
    )


async def load_recent_records(
    session: AsyncSession, patient_id, before_date: date, limit: int = HISTORY_WINDOW
) -> tuple[DailyRecord, ...]:
    """Most-recent-first, strictly before `before_date`, current versions only."""
    rows = (
        await session.execute(
            select(CheckIn)
            .where(
                CheckIn.patient_id == patient_id,
                CheckIn.checkin_date < before_date,
                CheckIn.is_current.is_(True),
            )
            .order_by(CheckIn.checkin_date.desc())
            .limit(limit)
        )
    ).scalars().all()
    return tuple(_to_daily_record(r) for r in rows)


async def load_open_flag_levels_excluding_note(session: AsyncSession, patient_id) -> frozenset[FlagLevel]:
    """Feeds PatientHistory.open_flag_levels -- used by R10's "nothing
    open" gate. Note-level flags are recorded but are not work (spec
    section 8), so they must not block R10 from firing.
    """
    rows = (
        await session.execute(
            select(Flag.level).where(
                Flag.patient_id == patient_id,
                Flag.status.in_(OPEN_STATUSES),
                Flag.level != FlagLevel.NOTE,
            )
        )
    ).scalars().all()
    return frozenset(rows)


async def load_open_flags(session: AsyncSession, patient_id) -> list[OpenFlagView]:
    """Feeds flags.reconcile()'s 72h dedup check -- every open flag,
    every level, including Note (a repeat Note firing should still
    collapse into the same flag rather than spawning a new one).
    """
    rows = (
        await session.execute(
            select(Flag).where(Flag.patient_id == patient_id, Flag.status.in_(OPEN_STATUSES))
        )
    ).scalars().all()
    return [
        OpenFlagView(flag_id=f.id, rule_code=f.rule_code, level=f.level, last_fired_at=f.last_fired_at)
        for f in rows
    ]


async def load_active_rules(session: AsyncSession, as_of: datetime | None = None) -> list[RuleDefinition]:
    as_of = as_of or datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(RuleDefinitionRow).where(
                RuleDefinitionRow.is_active.is_(True),
                RuleDefinitionRow.effective_from <= as_of,
                (RuleDefinitionRow.effective_to.is_(None)) | (RuleDefinitionRow.effective_to > as_of),
            )
        )
    ).scalars().all()
    return [
        RuleDefinition(
            rule_code=r.rule_code,
            version=r.version,
            level=r.level,
            description=r.description,
            rule_type=r.rule_type,
            params=r.params,
            follow_up_questions=tuple(r.follow_up_questions or ()),
            requires_fever_gate=r.requires_fever_gate,
            care_manager_action=r.care_manager_action,
        )
        for r in rows
        # D3-09 (no-checkin streak) never runs through the submission
        # path -- see app/jobs/no_checkin_timer.py.
        if r.rule_type != "no_checkin_streak"
    ]


async def build_context(
    session: AsyncSession,
    patient: Patient,
    checkin_row: CheckIn,
) -> CheckinContext:
    today = _to_daily_record(checkin_row)
    recent = await load_recent_records(session, patient.id, before_date=checkin_row.checkin_date)
    prior_scores = [r.today_score for r in recent]
    usual = usual_score(prior_scores)
    change = score_change(today.today_score, usual)
    open_levels = await load_open_flag_levels_excluding_note(session, patient.id)
    history = PatientHistory(
        on_biologic=patient.current_drug.is_biologic_or_similar,
        open_flag_levels=open_levels,
        recent_records=recent,
    )
    return CheckinContext(today=today, usual_score=usual, change=change, history=history)
