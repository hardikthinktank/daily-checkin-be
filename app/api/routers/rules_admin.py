"""Rule administration (spec section 5): rules are DB rows so they can
be edited and approved without a code release.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common_responses import NOT_FOUND, UNPROCESSABLE
from app.api.deps import get_db
from app.schemas.rules import RuleDefinitionResponse, RuleVersionCreateRequest
from app.services import rule_admin_service
from app.services.errors import NotFoundError

router = APIRouter(tags=["Rule administration"])


@router.get(
    "/admin/rules",
    response_model=list[RuleDefinitionResponse],
    summary="List rule versions",
)
async def list_rules(
    active_only: bool = Query(True, description="If true, only the currently-effective version of each rule_code."),
    db: AsyncSession = Depends(get_db),
) -> list[RuleDefinitionResponse]:
    rows = await rule_admin_service.list_rules(db, active_only=active_only)
    return [RuleDefinitionResponse.model_validate(r) for r in rows]


@router.get(
    "/admin/rules/{rule_id}",
    response_model=RuleDefinitionResponse,
    summary="Get one specific rule version by its row ID",
    responses={**NOT_FOUND},
)
async def get_rule(rule_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> RuleDefinitionResponse:
    row = await rule_admin_service.get_rule(db, rule_id)
    if row is None:
        raise NotFoundError(detail={"rule_id": str(rule_id)})
    return RuleDefinitionResponse.model_validate(row)


@router.post(
    "/admin/rules",
    response_model=RuleDefinitionResponse,
    summary="Create a new version of a rule (or a brand-new rule_code)",
    description=(
        "Never mutates a version that may already have fired. If rule_code already has an "
        "active version, it is closed out (effective_to = now) and this becomes the new "
        "active version; otherwise this becomes version 1. params is validated against the "
        "keys rule_type actually reads (see GET /admin/rules for worked examples per "
        "rule_type) -- a mismatch is rejected here with 422 invalid_rule_params rather than "
        "being allowed to go active and fail for every patient on next use."
    ),
    responses={**UNPROCESSABLE},
)
async def create_rule_version(
    body: RuleVersionCreateRequest, db: AsyncSession = Depends(get_db)
) -> RuleDefinitionResponse:
    row = await rule_admin_service.create_new_version(
        db,
        rule_code=body.rule_code,
        level=body.level.value,
        description=body.description,
        rule_type=body.rule_type,
        params=body.params,
        follow_up_questions=body.follow_up_questions,
        requires_fever_gate=body.requires_fever_gate,
        care_manager_action=body.care_manager_action,
        threshold_source=body.threshold_source,
    )
    return RuleDefinitionResponse.model_validate(row)
