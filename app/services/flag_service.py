"""Everything the care manager console needs (spec section 8): the work
list, "why it fired", and the four actions (acknowledge, log a call,
escalate, resolve).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Actor, ActorType, CareAction, CareActionType, Flag, FlagLevel, FlagStatus
from app.services.errors import (
    ActorNotFoundError,
    ConcurrentAcknowledgeError,
    FlagAlreadyResolvedError,
    FlagNotFoundError,
    SystemActorForbiddenError,
)
from app.services.rule_descriptions import describe_rule

# Work-list ordering: Critical first, then by how recent (spec section 8).
_LEVEL_SORT_ORDER = {FlagLevel.CRITICAL: 0, FlagLevel.URGENT: 1, FlagLevel.REVIEW: 2, FlagLevel.NOTE: 3}


async def _load_flag(session: AsyncSession, flag_id: uuid.UUID) -> Flag:
    flag = await session.get(Flag, flag_id)
    if flag is None:
        raise FlagNotFoundError(detail={"flag_id": str(flag_id)})
    return flag


async def _load_actor(session: AsyncSession, actor_id: uuid.UUID) -> Actor:
    actor = await session.get(Actor, actor_id)
    if actor is None:
        raise ActorNotFoundError(detail={"actor_id": str(actor_id)})
    return actor


async def get_work_list(session: AsyncSession) -> list[Flag]:
    """Every patient with something open, sorted by level then recency.
    Notes never appear here -- they are recorded but they are not work
    (spec section 8).
    """
    rows = (
        await session.execute(
            select(Flag)
            .where(Flag.status != FlagStatus.RESOLVED, Flag.level != FlagLevel.NOTE)
            .order_by(Flag.last_fired_at.desc())
        )
    ).scalars().all()
    return sorted(rows, key=lambda f: (_LEVEL_SORT_ORDER[f.level], -f.last_fired_at.timestamp()))


async def get_flag_detail(session: AsyncSession, flag_id: uuid.UUID) -> tuple[Flag, str, str]:
    """Returns (flag, rule_description, care_manager_action) -- "why it
    fired" per spec section 8: rule ID, rule version, description
    sentence, and the numbers, all present on the Flag/FlagEvent rows
    already.
    """
    flag = await _load_flag(session, flag_id)
    description, action = await describe_rule(session, flag.rule_code, flag.rule_version)
    return flag, description, action


async def acknowledge(session: AsyncSession, flag_id: uuid.UUID, actor_id: uuid.UUID) -> Flag:
    """Spec section 8: "two people clicking at once: the second gets an
    error rather than silently overwriting the first." Implemented as a
    single conditional UPDATE so the race is resolved by the database,
    not by a read-then-write in application code.
    """
    await _load_actor(session, actor_id)
    flag = await _load_flag(session, flag_id)
    if flag.status == FlagStatus.RESOLVED:
        raise FlagAlreadyResolvedError(detail={"flag_id": str(flag_id)})

    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Flag)
        .where(Flag.id == flag_id, Flag.acknowledged_by.is_(None))
        .values(acknowledged_by=actor_id, acknowledged_at=now, status=FlagStatus.ACKNOWLEDGED)
    )
    if result.rowcount == 0:
        raise ConcurrentAcknowledgeError(detail={"flag_id": str(flag_id)})

    await session.commit()
    await session.refresh(flag)
    return flag


async def log_call(
    session: AsyncSession,
    flag_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    minutes: int,
    call_type: str,
    note: str | None = None,
) -> CareAction:
    """Spec: "only a human can add minutes." Checked here (fast, clear
    error message) AND enforced by the `reject_system_minutes` database
    trigger (T13) -- the app check is a nicety, the trigger is the actual
    guarantee.
    """
    flag = await _load_flag(session, flag_id)
    actor = await _load_actor(session, actor_id)
    if actor.actor_type == ActorType.SYSTEM:
        raise SystemActorForbiddenError(detail={"actor_id": str(actor_id)})

    action = CareAction(
        flag_id=flag.id,
        actor_id=actor.id,
        action_type=CareActionType.LOG_CALL,
        minutes=minutes,
        call_type=call_type,
        note=note,
        organisation_id=actor.organisation_id,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action


async def escalate(session: AsyncSession, flag_id: uuid.UUID, actor_id: uuid.UUID, reason: str) -> CareAction:
    flag = await _load_flag(session, flag_id)
    actor = await _load_actor(session, actor_id)

    flag.status = FlagStatus.ESCALATED
    action = CareAction(
        flag_id=flag.id,
        actor_id=actor.id,
        action_type=CareActionType.ESCALATE,
        reason=reason,
        organisation_id=actor.organisation_id,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action


async def resolve(session: AsyncSession, flag_id: uuid.UUID, actor_id: uuid.UUID, note: str) -> CareAction:
    """Closes with a note. Nothing is deleted; the whole history stays
    (spec section 8) -- the Flag row's status simply moves to resolved.
    """
    flag = await _load_flag(session, flag_id)
    actor = await _load_actor(session, actor_id)

    flag.status = FlagStatus.RESOLVED
    action = CareAction(
        flag_id=flag.id,
        actor_id=actor.id,
        action_type=CareActionType.RESOLVE,
        note=note,
        organisation_id=actor.organisation_id,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action
