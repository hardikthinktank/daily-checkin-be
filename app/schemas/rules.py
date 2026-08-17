"""Request/response models for rule administration (spec section 5).
Editing a rule creates a new version rather than mutating an existing
one -- see app/services/rule_admin_service.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.rules.strategies import STRATEGY_REGISTRY
from app.domain.rules.types import FOLLOWUP_QUESTION_CODES, FlagLevel

KNOWN_RULE_TYPES = sorted({*STRATEGY_REGISTRY.keys(), "no_checkin_streak"})


class RuleDefinitionResponse(BaseModel):
    id: uuid.UUID
    rule_code: str
    version: int
    level: FlagLevel
    description: str
    rule_type: str
    params: dict
    follow_up_questions: list[str]
    requires_fever_gate: bool
    care_manager_action: str
    threshold_source: str = Field(
        ..., description='"demo-placeholder" until a clinical source and sign-off are recorded (spec section 12).'
    )
    effective_from: datetime
    effective_to: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class RuleVersionCreateRequest(BaseModel):
    """POSTing this always creates a NEW version. If `rule_code` already
    has an active version, it is closed out (its `effective_to` is set to
    now) and this becomes the new active version. If `rule_code` has
    never been seen before, this becomes version 1.
    """

    rule_code: str = Field(..., min_length=1, max_length=32, examples=["D3-01"])
    level: FlagLevel
    description: str = Field(
        ..., min_length=1, max_length=500, description='The sentence a care manager sees as "why it fired".'
    )
    rule_type: str = Field(
        ...,
        description=(
            f"One of the engine's known rule shapes: {KNOWN_RULE_TYPES}. Each shape reads specific "
            "keys out of params -- see REQUIRED_PARAMS in app/domain/rules/strategies.py, or just "
            "match the worked example below. A mismatch is rejected with 422 invalid_rule_params, "
            "not silently accepted."
        ),
        examples=["threshold_gte"],
    )
    params: dict = Field(
        ...,
        description=(
            'Strategy-specific parameters -- REQUIRED, no default. Do not submit this endpoint with '
            'the Swagger placeholder ({"additionalProp1": {}}) still in place; params must contain '
            "exactly the keys rule_type needs, e.g. threshold_gte needs {\"field\": ..., \"gte\": ...}."
        ),
        examples=[{"field": "pain", "gte": 7}],
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description=f"Question codes from the fixed set the patient app knows how to render: {sorted(FOLLOWUP_QUESTION_CODES)}.",
    )
    requires_fever_gate: bool = Field(
        False, description="True if 'fever' in follow_up_questions should be dropped for non-biologic patients."
    )
    care_manager_action: str = Field("", description="What the care manager is expected to do when this fires.")
    threshold_source: str = Field(
        "demo-placeholder",
        description="Clinical citation once this threshold is validated; otherwise leave as demo-placeholder.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "rule_code": "D3-01",
                    "level": "Review",
                    "description": "Pain is 7 or higher.",
                    "rule_type": "threshold_gte",
                    "params": {"field": "pain", "gte": 7},
                    "follow_up_questions": ["days_at_level", "new_joint", "fever"],
                    "requires_fever_gate": True,
                    "care_manager_action": "Review within one business day.",
                    "threshold_source": "demo-placeholder",
                }
            ]
        }
    }

    @field_validator("follow_up_questions")
    @classmethod
    def _questions_must_be_known_codes(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - FOLLOWUP_QUESTION_CODES)
        if unknown:
            raise ValueError(
                f"unknown follow-up question code(s) {unknown}; must be one of {sorted(FOLLOWUP_QUESTION_CODES)}"
            )
        return value
