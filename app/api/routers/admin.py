"""The admin list (spec section 9)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.admin import AdminListRowResponse
from app.services import admin_list_service

router = APIRouter(tags=["Admin list"])


@router.get(
    "/admin/patients",
    response_model=list[AdminListRowResponse],
    summary="One row per patient, no drilling required",
    description=(
        "Spec section 9. The 16-day marker and live-call marker are facts about the record "
        "for operational visibility -- NOT a billing decision; do not present them as one."
    ),
)
async def get_admin_list(
    month: date | None = Query(
        None, description="Any date within the target month. Defaults to the current month."
    ),
    db: AsyncSession = Depends(get_db),
) -> list[AdminListRowResponse]:
    rows = await admin_list_service.get_admin_list(db, month or date.today())
    return [AdminListRowResponse.from_row(r) for r in rows]
