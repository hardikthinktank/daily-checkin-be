"""The monthly summary for the physician (spec section 10)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common_responses import NOT_FOUND
from app.api.deps import get_db
from app.schemas.summary import MonthlySummaryResponse
from app.services import summary_service

router = APIRouter(tags=["Monthly summary"])


@router.get(
    "/patients/{patient_id}/monthly-summary",
    response_model=MonthlySummaryResponse,
    summary="One page of charts for a calendar month",
    description=(
        "Spec section 10: readable in under two minutes, meant to print. Served from a "
        "pre-built cache (refreshed on every relevant write) so this is normally well under "
        "the five-second target; a cache miss falls back to a synchronous build."
    ),
    responses={**NOT_FOUND},
)
async def get_monthly_summary(
    patient_id: uuid.UUID,
    month: date | None = Query(None, description="Any date within the target month. Defaults to the current month."),
    db: AsyncSession = Depends(get_db),
) -> MonthlySummaryResponse:
    payload = await summary_service.get_summary(db, patient_id, month or date.today())
    return MonthlySummaryResponse.model_validate(payload)


@router.post(
    "/patients/{patient_id}/monthly-summary/rebuild",
    response_model=MonthlySummaryResponse,
    summary="Force a fresh rebuild of the cached summary",
    description="Mainly for demos/testing -- production traffic should rely on the automatic rebuild-on-write.",
    responses={**NOT_FOUND},
)
async def rebuild_monthly_summary(
    patient_id: uuid.UUID,
    month: date | None = Query(None, description="Any date within the target month. Defaults to the current month."),
    db: AsyncSession = Depends(get_db),
) -> MonthlySummaryResponse:
    payload = await summary_service.generate_and_cache(db, patient_id, month or date.today())
    return MonthlySummaryResponse.model_validate(payload)
