"""Request/response models for the patient check-in flow (spec sections
2, 3, 4, 6). Follow-up answers are modelled as one explicit field per
question, each a fixed Literal choice plus "skipped" -- matching the
spec's "no free typing on any of these, every answer is a button"
(section 6) as closely as OpenAPI can express it, so the frontend gets a
real enum picker per field instead of a free-text dict.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.rules.types import FlagLevel

DaysAtLevel = Literal["1", "2-3", "4-7", "more than 7"]
NewJoint = Literal["yes", "no", "not sure"]
Joint = Literal["hands", "wrists", "elbows", "shoulders", "knees", "ankles", "feet"]
MorningStiffness = Literal["under 30 min", "30-60 min", "over 60 min"]
Sleep = Literal["fine", "broken", "poor most nights"]
YesNo = Literal["yes", "no"]
Reason = Literal["cost", "side effects", "forgot", "ran out", "other"]
Skipped = Literal["skipped"]


class CheckinSubmitRequest(BaseModel):
    """The three daily questions (spec section 3). All three are
    required -- a submission missing one is rejected by field validation
    before it ever reaches the rule engine.
    """

    client_submission_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Random ID the phone attaches to this submission (spec section 3). "
            "Resending the SAME id (e.g. after losing signal mid-submit) is "
            "always safe: the server saves it once and returns the original "
            "result, never a duplicate record or a duplicate flag."
        ),
        examples=["a3f1c2e8-6b7d-4e9a-9c1a-2f6b8e0d4c11"],
    )
    fatigue: int = Field(..., ge=1, le=10, description="How tired have you been today? 1 (none) to 10 (worst).")
    pain: int = Field(..., ge=1, le=10, description="How much joint pain today? 1 (none) to 10 (worst).")
    swelling: int = Field(..., ge=1, le=10, description="How swollen are your joints today? 1 (none) to 10 (worst).")
    checkin_date: date | None = Field(
        None,
        description="Defaults to today (server time) if omitted. Override only for backfill/testing.",
    )


class FollowupAnswersRequest(BaseModel):
    """Answers to whichever follow-up questions a fired rule asked for
    (spec section 6). Send only the fields that apply -- the endpoint
    that returns `required_followups` tells you which ones. Any field
    can be set to "skipped" instead of a real answer; a skipped question
    is recorded as skipped, not as missing.
    """

    days_at_level: DaysAtLevel | Skipped | None = Field(
        None, description="How many days has the pain been at this level? Asked by R1."
    )
    new_joint: NewJoint | Skipped | None = Field(
        None, description="Is a new joint involved that wasn't before? Asked by R1."
    )
    which_joints: list[Joint] | Skipped | None = Field(
        None, description="Which joints are swollen today? Pick any. Asked by R2."
    )
    morning_stiffness: MorningStiffness | Skipped | None = Field(
        None, description="How long did morning stiffness last today? Asked by R2; also feeds R7."
    )
    sleep: Sleep | Skipped | None = Field(None, description="How has your sleep been this week? Asked by R3.")
    medication: YesNo | Skipped | None = Field(
        None, description="Did you take your medication as prescribed this week? Asked by R4."
    )
    reason: Reason | Skipped | None = Field(
        None, description="What got in the way? Asked by R8, only when medication = no."
    )
    fever: YesNo | Skipped | None = Field(
        None,
        description=(
            "Have you had a fever or felt feverish in the last 24 hours? Only ever asked of "
            "patients on a biologic or similar drug. A 'yes' here is Critical, always (spec section 7)."
        ),
    )

    def to_answer_dict(self) -> dict[str, str]:
        raw = self.model_dump(exclude_none=True)
        return {k: (",".join(v) if isinstance(v, list) else v) for k, v in raw.items()}


class CheckinResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    checkin_date: date
    fatigue: int
    pain: int
    swelling: int
    today_score: float = Field(..., description="(fatigue + pain + swelling) / 3, rounded to one decimal.")
    usual_score: float | None = Field(
        None, description="Median of the patient's last 14 scores. Null until the patient has 5+ prior check-ins."
    )
    change: float | None = Field(None, description="today_score - usual_score. Null whenever usual_score is null.")
    follow_up_answers: dict = Field(default_factory=dict, description="Follow-up answers collected so far, keyed by question code.")
    version: int = Field(..., description="1 for the first submission this day; incremented on same-day resubmission.")
    is_current: bool
    submitted_at: datetime

    required_followups: list[str] = Field(
        default_factory=list,
        description=(
            "Follow-up question codes still needed before every fired rule has what it asked "
            "for. Empty means nothing further is required for today. POST these to "
            "/checkins/{id}/followups."
        ),
    )
    day_level: FlagLevel | None = Field(
        None, description="Highest flag level triggered by this submission so far (across all rules that fired today)."
    )
    created: bool = Field(
        ...,
        description=(
            "False when this response is a replay of an already-processed submission (same "
            "client_submission_id sent twice, or a follow-up-answers amendment) -- no new "
            "check-in record or flag was created by this call."
        ),
    )

    model_config = {"from_attributes": True}

    @classmethod
    def from_result(cls, result) -> "CheckinResponse":
        """`result` is a checkin_service.CheckinResult -- kept as a loose
        type hint here to avoid services -> schemas -> services import
        cycles; the router layer is what actually ties the two together.
        """
        checkin = result.checkin
        return cls(
            id=checkin.id,
            patient_id=checkin.patient_id,
            checkin_date=checkin.checkin_date,
            fatigue=checkin.fatigue,
            pain=checkin.pain,
            swelling=checkin.swelling,
            today_score=float(checkin.today_score),
            usual_score=float(checkin.usual_score) if checkin.usual_score is not None else None,
            change=float(checkin.change) if checkin.change is not None else None,
            follow_up_answers=checkin.follow_up_answers,
            version=checkin.version,
            is_current=checkin.is_current,
            submitted_at=checkin.submitted_at,
            required_followups=list(result.required_followups),
            day_level=result.day_level,
            created=result.created,
        )
