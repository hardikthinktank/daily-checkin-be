"""Reference data (patients, drugs, actors). Not part of the spec's four
screens directly, but every one of those screens needs somewhere to look
these up, and something has to be able to create them -- exposed here so
a frontend has a real provisioning path instead of only the seed
scripts.
"""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.db.models import ActorRole, ActorType


class DrugResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_biologic_or_similar: bool = Field(
        ..., description="Gates whether the fever follow-up question is ever asked (spec section 5)."
    )

    model_config = {"from_attributes": True}


class DrugCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, examples=["Adalimumab (biologic)"])
    is_biologic_or_similar: bool = Field(
        ..., description="Gates whether the fever follow-up question is ever asked (spec section 5)."
    )


class PatientResponse(BaseModel):
    id: uuid.UUID
    name: str
    mrn: str
    diagnosis: str
    current_drug: DrugResponse
    enrollment_date: date

    model_config = {"from_attributes": True}


class PatientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    mrn: str = Field(..., min_length=1, max_length=64, description="Must be unique.")
    diagnosis: str = Field(..., min_length=1, max_length=200)
    current_drug_id: uuid.UUID = Field(..., description="Must reference an existing drug -- see GET /drugs.")
    enrollment_date: date | None = Field(None, description="Defaults to today if omitted.")


class ActorResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    actor_type: ActorType = Field(..., description="'system' actors can never log calls or record minutes (spec T13).")
    role: ActorRole

    model_config = {"from_attributes": True}


class ActorCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    actor_type: ActorType = Field(
        ..., description="'system' actors can never log calls or record minutes (spec T13) -- use 'human' for real staff."
    )
    role: ActorRole
