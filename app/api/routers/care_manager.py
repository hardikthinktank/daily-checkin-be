"""Care manager console endpoints (spec section 8): the work list, "why
it fired", and the four actions.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common_responses import CONFLICT, FORBIDDEN, NOT_FOUND, UNPROCESSABLE
from app.api.deps import get_db
from app.db.models import Flag
from app.jobs.summary_prebuild import rebuild_current_month_for_patient
from app.schemas.flags import (
    AcknowledgeRequest,
    CareActionResponse,
    EscalateRequest,
    FlagDetailResponse,
    FlagEventResponse,
    FlagResponse,
    LogCallRequest,
    ResolveRequest,
)
from app.services import flag_service

router = APIRouter(tags=["Care manager console"])


@router.get(
    "/care-manager/worklist",
    response_model=list[FlagResponse],
    summary="Every patient with something open",
    description=(
        "Sorted by level first (Critical at the top) and recency second. Note-level flags "
        "never appear here -- they are recorded but they are not work (spec section 8)."
    ),
)
async def get_worklist(db: AsyncSession = Depends(get_db)) -> list[FlagResponse]:
    flags = await flag_service.get_work_list(db)
    return [FlagResponse.model_validate(f) for f in flags]


@router.get(
    "/flags/{flag_id}",
    response_model=FlagDetailResponse,
    summary='"Why it fired", plus every event and action on this flag',
    responses={**NOT_FOUND},
)
async def get_flag_detail(flag_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FlagDetailResponse:
    flag, description, care_manager_action = await flag_service.get_flag_detail(db, flag_id)
    return FlagDetailResponse(
        **FlagResponse.model_validate(flag).model_dump(),
        rule_description=description,
        care_manager_action=care_manager_action,
        events=[FlagEventResponse.model_validate(e) for e in flag.events],
        actions=[CareActionResponse.model_validate(a) for a in flag.actions],
    )


@router.post(
    "/flags/{flag_id}/acknowledge",
    response_model=FlagResponse,
    summary="Claim this flag",
    description=(
        "Records who took it and when. If two people click at once, the second request gets "
        "409 Conflict instead of silently overwriting the first acknowledgement (spec section 8)."
    ),
    responses={**NOT_FOUND, **CONFLICT},
)
async def acknowledge_flag(
    flag_id: uuid.UUID, body: AcknowledgeRequest, db: AsyncSession = Depends(get_db)
) -> FlagResponse:
    flag = await flag_service.acknowledge(db, flag_id, body.actor_id)
    return FlagResponse.model_validate(flag)


@router.post(
    "/flags/{flag_id}/log-call",
    response_model=CareActionResponse,
    summary="Log a call and record minutes",
    description=(
        "Only a human actor may call this (spec: 'only a human can add minutes'). A system "
        "actor gets 403 here, and would additionally be rejected by the database itself even "
        "if this check were bypassed -- see the reject_system_minutes trigger (T13)."
    ),
    responses={**NOT_FOUND, **FORBIDDEN},
)
async def log_call(
    flag_id: uuid.UUID,
    body: LogCallRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CareActionResponse:
    flag = await db.get(Flag, flag_id)
    action = await flag_service.log_call(
        db, flag_id, body.actor_id, minutes=body.minutes, call_type=body.call_type, note=body.note
    )
    if flag is not None:
        background_tasks.add_task(_rebuild_summary_quietly, flag.patient_id)
    return CareActionResponse.model_validate(action)


@router.post(
    "/flags/{flag_id}/escalate",
    response_model=CareActionResponse,
    summary="Send to the physician for same-day review",
    responses={**NOT_FOUND},
)
async def escalate_flag(
    flag_id: uuid.UUID,
    body: EscalateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CareActionResponse:
    flag = await db.get(Flag, flag_id)
    action = await flag_service.escalate(db, flag_id, body.actor_id, body.reason)
    if flag is not None:
        background_tasks.add_task(_rebuild_summary_quietly, flag.patient_id)
    return CareActionResponse.model_validate(action)


@router.post(
    "/flags/{flag_id}/resolve",
    response_model=CareActionResponse,
    summary="Close with a note",
    description="Nothing is deleted; the whole history stays on the flag (spec section 8).",
    responses={**NOT_FOUND, **UNPROCESSABLE},
)
async def resolve_flag(
    flag_id: uuid.UUID,
    body: ResolveRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CareActionResponse:
    flag = await db.get(Flag, flag_id)
    action = await flag_service.resolve(db, flag_id, body.actor_id, body.note)
    if flag is not None:
        background_tasks.add_task(_rebuild_summary_quietly, flag.patient_id)
    return CareActionResponse.model_validate(action)


async def _rebuild_summary_quietly(patient_id: uuid.UUID) -> None:
    from app.db.base import SessionLocal

    async with SessionLocal() as session:
        await rebuild_current_month_for_patient(session, patient_id)
