"""Patient app endpoints (spec sections 2, 3, 6): submit the three daily
answers, then answer whatever follow-up questions the fired rules asked
for.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common_responses import NOT_FOUND, UNPROCESSABLE
from app.api.deps import get_db
from app.jobs.summary_prebuild import rebuild_current_month_for_patient
from app.schemas.checkins import CheckinResponse, CheckinSubmitRequest, FollowupAnswersRequest
from app.services import checkin_service
from app.services.errors import PatientNotFoundError

router = APIRouter(tags=["Patient check-ins"])


@router.post(
    "/patients/{patient_id}/checkins",
    response_model=CheckinResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit today's three daily answers",
    description=(
        "The patient app's only write path (spec section 2, steps 1-3). Runs the score "
        "calculation, the full rule table, and the two built-in failsafes, and returns which "
        "follow-up questions (if any) still need answers. Safe to retry with the same "
        "client_submission_id if the phone loses signal mid-submit -- see that field's "
        "description."
    ),
    responses={**NOT_FOUND, **UNPROCESSABLE},
)
async def submit_checkin(
    patient_id: uuid.UUID,
    body: CheckinSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CheckinResponse:
    result = await checkin_service.submit_checkin(
        db,
        patient_id,
        client_submission_id=body.client_submission_id,
        fatigue=body.fatigue,
        pain=body.pain,
        swelling=body.swelling,
        checkin_date=body.checkin_date,
    )
    background_tasks.add_task(_rebuild_summary_quietly, patient_id)
    return CheckinResponse.from_result(result)


@router.post(
    "/checkins/{checkin_id}/followups",
    response_model=CheckinResponse,
    summary="Answer the follow-up questions a rule asked for",
    description=(
        "Spec section 2, step 4: the patient answers on the same screen and the rules run "
        "again with those answers included. This is what lets a 'fever: yes' answer turn an "
        "Urgent day into a Critical one. Send only the fields you have answers for; anything "
        "the patient explicitly declines should be sent as \"skipped\", not omitted."
    ),
    responses={**NOT_FOUND},
)
async def submit_followups(
    checkin_id: uuid.UUID,
    body: FollowupAnswersRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CheckinResponse:
    result = await checkin_service.submit_followups(db, checkin_id, body.to_answer_dict())
    background_tasks.add_task(_rebuild_summary_quietly, result.checkin.patient_id)
    return CheckinResponse.from_result(result)


async def _rebuild_summary_quietly(patient_id: uuid.UUID) -> None:
    """Runs after the response has already been sent (spec section 10:
    the summary should be ready before the visit, not built at click
    time). Uses its own session -- BackgroundTasks run after the
    request's session has already closed.
    """
    from app.db.base import SessionLocal

    async with SessionLocal() as session:
        try:
            await rebuild_current_month_for_patient(session, patient_id)
        except PatientNotFoundError:
            pass
