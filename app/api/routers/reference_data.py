"""Reference data -- patients, drugs, actors. Not one of the spec's four
screens, but every one of those screens needs somewhere to look these up,
and something has to be able to create them in the first place.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common_responses import DUPLICATE, NOT_FOUND
from app.api.deps import get_db
from app.db.models import Actor, Drug, Patient
from app.schemas.reference_data import (
    ActorCreateRequest,
    ActorResponse,
    DrugCreateRequest,
    DrugResponse,
    PatientCreateRequest,
    PatientResponse,
)
from app.services.errors import DrugNotFoundError, DuplicateDrugNameError, DuplicateMrnError, PatientNotFoundError

router = APIRouter(tags=["Reference data"])


@router.get("/patients", response_model=list[PatientResponse], summary="List all patients")
async def list_patients(db: AsyncSession = Depends(get_db)) -> list[PatientResponse]:
    rows = (await db.execute(select(Patient).order_by(Patient.name))).scalars().all()
    return [PatientResponse.model_validate(p) for p in rows]


@router.get("/patients/{patient_id}", response_model=PatientResponse, responses={**NOT_FOUND})
async def get_patient(patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PatientResponse:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise PatientNotFoundError(detail={"patient_id": str(patient_id)})
    return PatientResponse.model_validate(patient)


@router.post(
    "/patients",
    response_model=PatientResponse,
    status_code=201,
    summary="Enroll a new patient",
    description="mrn must be unique; current_drug_id must reference an existing drug (see GET /drugs, or POST /drugs to create one).",
    responses={**NOT_FOUND, **DUPLICATE},
)
async def create_patient(body: PatientCreateRequest, db: AsyncSession = Depends(get_db)) -> PatientResponse:
    drug = await db.get(Drug, body.current_drug_id)
    if drug is None:
        raise DrugNotFoundError(detail={"current_drug_id": str(body.current_drug_id)})

    patient = Patient(
        name=body.name,
        mrn=body.mrn,
        diagnosis=body.diagnosis,
        current_drug_id=body.current_drug_id,
        enrollment_date=body.enrollment_date or date.today(),
    )
    db.add(patient)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise DuplicateMrnError(detail={"mrn": body.mrn}) from e
    await db.refresh(patient, attribute_names=["current_drug"])
    return PatientResponse.model_validate(patient)


@router.get("/drugs", response_model=list[DrugResponse], summary="List all drugs")
async def list_drugs(db: AsyncSession = Depends(get_db)) -> list[DrugResponse]:
    rows = (await db.execute(select(Drug).order_by(Drug.name))).scalars().all()
    return [DrugResponse.model_validate(d) for d in rows]


@router.post(
    "/drugs",
    response_model=DrugResponse,
    status_code=201,
    summary="Add a drug",
    description="is_biologic_or_similar gates whether the fever follow-up question is ever asked (spec section 5).",
    responses={**DUPLICATE},
)
async def create_drug(body: DrugCreateRequest, db: AsyncSession = Depends(get_db)) -> DrugResponse:
    drug = Drug(name=body.name, is_biologic_or_similar=body.is_biologic_or_similar)
    db.add(drug)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise DuplicateDrugNameError(detail={"name": body.name}) from e
    await db.refresh(drug)
    return DrugResponse.model_validate(drug)


@router.get(
    "/actors",
    response_model=list[ActorResponse],
    summary="List all actors",
    description="Care managers, physicians, and system accounts. System accounts can never log calls or record minutes (T13).",
)
async def list_actors(db: AsyncSession = Depends(get_db)) -> list[ActorResponse]:
    rows = (await db.execute(select(Actor).order_by(Actor.display_name))).scalars().all()
    return [ActorResponse.model_validate(a) for a in rows]


@router.post(
    "/actors",
    response_model=ActorResponse,
    status_code=201,
    summary="Add an actor",
    description="Create a care manager, physician, or system account. Use actor_type='human' for real staff.",
)
async def create_actor(body: ActorCreateRequest, db: AsyncSession = Depends(get_db)) -> ActorResponse:
    actor = Actor(display_name=body.display_name, actor_type=body.actor_type, role=body.role)
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    return ActorResponse.model_validate(actor)
