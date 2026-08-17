"""Request/response models for the care manager console (spec section
8): the work list, "why it fired", and the four actions.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models import CallType, CareActionType, FlagStatus
from app.domain.rules.types import FlagLevel


class FlagEventResponse(BaseModel):
    id: uuid.UUID
    checkin_id: uuid.UUID | None = Field(
        None, description="Null for timer-fired rules (currently only R9, three days with no check-in)."
    )
    rule_version: str
    fired_at: datetime
    numbers_snapshot: dict = Field(..., description="The exact numbers that satisfied the rule on this firing.")

    model_config = {"from_attributes": True}


class CareActionResponse(BaseModel):
    id: uuid.UUID
    flag_id: uuid.UUID
    actor_id: uuid.UUID
    action_type: CareActionType
    minutes: int | None = None
    call_type: CallType | None = None
    reason: str | None = None
    note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FlagResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    rule_code: str = Field(..., examples=["D3-01", "FAILSAFE-FEVER"])
    rule_version: str = Field(
        ..., description='The DB rule version ("1", "2", ...) or "builtin-1" for a section-7 failsafe firing.'
    )
    level: FlagLevel
    status: FlagStatus
    first_fired_at: datetime
    last_fired_at: datetime
    event_count: int = Field(
        ..., description="Repeat firings within 72h of the last one add an event here instead of a new flag."
    )
    why_snapshot: dict = Field(..., description="Numbers from the most recent firing.")
    acknowledged_by: uuid.UUID | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlagDetailResponse(FlagResponse):
    rule_description: str = Field(..., description='The human sentence describing the rule, e.g. "Pain is 7 or higher."')
    care_manager_action: str = Field("", description="What the care manager is expected to do, per the rule definition.")
    events: list[FlagEventResponse] = Field(default_factory=list)
    actions: list[CareActionResponse] = Field(default_factory=list)


class AcknowledgeRequest(BaseModel):
    actor_id: uuid.UUID = Field(..., description="Must be a human actor's ID.")


class LogCallRequest(BaseModel):
    actor_id: uuid.UUID = Field(..., description="Must be a human actor's ID -- system actors are rejected (spec T13).")
    minutes: int = Field(..., ge=0, description="Minutes spent on this contact.")
    call_type: CallType = Field(
        ...,
        description=(
            "phone/video count as a live interaction and turn on the patient's monthly "
            "live-call marker. async_message never does, however many messages went back "
            "and forth (spec, 'time recording')."
        ),
    )
    note: str | None = Field(None, max_length=2000)


class EscalateRequest(BaseModel):
    actor_id: uuid.UUID
    reason: str = Field(..., min_length=1, max_length=500, description="Sent to the physician along with the flag.")


class ResolveRequest(BaseModel):
    actor_id: uuid.UUID
    note: str = Field(..., min_length=1, max_length=2000, description="Closing note. Nothing is deleted; history stays.")
