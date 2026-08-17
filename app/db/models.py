"""SQLAlchemy models. This is the persistence mirror of the domain types
in app/domain/rules/types.py -- the service layer translates between the
two. This module is allowed to import from app.domain (one-way: domain
never imports this); FlagLevel in particular is imported straight from
the domain layer so a flag's level never needs converting back and forth
at the service-layer boundary.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.rules.types import FlagLevel  # re-exported for convenience

__all__ = [
    "FlagLevel",
    "FlagStatus",
    "ActorType",
    "ActorRole",
    "CareActionType",
    "CallType",
    "Drug",
    "Patient",
    "Actor",
    "RuleDefinition",
    "CheckIn",
    "CheckinFollowupLog",
    "Flag",
    "FlagEvent",
    "CareAction",
    "MonthlySummaryCache",
]


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class FlagStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class ActorType(str, enum.Enum):
    HUMAN = "human"
    SYSTEM = "system"


class ActorRole(str, enum.Enum):
    PATIENT = "patient"
    CARE_MANAGER = "care_manager"
    PHYSICIAN = "physician"
    ADMIN = "admin"
    SYSTEM = "system"


class CareActionType(str, enum.Enum):
    ACKNOWLEDGE = "acknowledge"
    LOG_CALL = "log_call"
    ESCALATE = "escalate"
    RESOLVE = "resolve"


class CallType(str, enum.Enum):
    PHONE = "phone"
    VIDEO = "video"
    ASYNC_MESSAGE = "async_message"


flag_level_enum = PGEnum(FlagLevel, name="flag_level", values_callable=lambda e: [m.value for m in e])
flag_status_enum = PGEnum(FlagStatus, name="flag_status", values_callable=lambda e: [m.value for m in e])
actor_type_enum = PGEnum(ActorType, name="actor_type", values_callable=lambda e: [m.value for m in e])
actor_role_enum = PGEnum(ActorRole, name="actor_role", values_callable=lambda e: [m.value for m in e])
care_action_type_enum = PGEnum(
    CareActionType, name="care_action_type", values_callable=lambda e: [m.value for m in e]
)
call_type_enum = PGEnum(CallType, name="call_type", values_callable=lambda e: [m.value for m in e])


class Drug(Base):
    __tablename__ = "drug"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_biologic_or_similar: Mapped[bool]

    patients: Mapped[list["Patient"]] = relationship(back_populates="current_drug")


class Patient(Base):
    __tablename__ = "patient"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    mrn: Mapped[str] = mapped_column(String(64), unique=True)
    diagnosis: Mapped[str] = mapped_column(String(200))
    current_drug_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drug.id"))
    enrollment_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # selectin: async sessions can't do implicit lazy-loads, and callers
    # (context_builder.build_context) always need is_biologic_or_similar.
    current_drug: Mapped[Drug] = relationship(back_populates="patients", lazy="selectin")
    checkins: Mapped[list["CheckIn"]] = relationship(back_populates="patient")
    flags: Mapped[list["Flag"]] = relationship(back_populates="patient")


class Actor(Base):
    """Anyone or anything that can act on a flag. `actor_type='system'`
    exists specifically so T13 has something to test against: the
    `reject_system_minutes` DB trigger (see migration
    0002_t13_reject_system_minutes) refuses any `log_call` CareAction
    whose actor is a system account, regardless of what the API layer
    does or doesn't check.
    """

    __tablename__ = "actor"

    id: Mapped[uuid.UUID] = _uuid_pk()
    display_name: Mapped[str] = mapped_column(String(200))
    actor_type: Mapped[ActorType] = mapped_column(actor_type_enum)
    role: Mapped[ActorRole] = mapped_column(actor_role_enum)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RuleDefinition(Base):
    """One version of one rule. Rows are never mutated once they have
    fired for anyone -- editing a rule means inserting a new version and
    closing out the previous one's `effective_to`, so "which version was
    in force on a given date" (spec section 5) is always reconstructable.
    """

    __tablename__ = "rule_definition"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_code: Mapped[str] = mapped_column(String(32))
    version: Mapped[int]
    level: Mapped[FlagLevel] = mapped_column(flag_level_enum)
    description: Mapped[str] = mapped_column(String(500))
    rule_type: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSONB)
    follow_up_questions: Mapped[list] = mapped_column(JSONB, default=list)
    requires_fever_gate: Mapped[bool] = mapped_column(default=False)
    care_manager_action: Mapped[str] = mapped_column(String(500), default="")
    threshold_source: Mapped[str] = mapped_column(
        String(64), default="demo-placeholder", server_default="demo-placeholder"
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("rule_code", "version", name="uq_rule_code_version"),)


class CheckIn(Base):
    """One (patient, date) submission. `is_current=True` marks the
    authoritative version for that day; a same-day resubmission with a
    new `client_submission_id` supersedes the previous row (which is
    kept, not deleted -- spec section 3).
    """

    __tablename__ = "checkin"

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    checkin_date: Mapped[date] = mapped_column(Date)
    client_submission_id: Mapped[str] = mapped_column(String(128), unique=True)

    fatigue: Mapped[int]
    pain: Mapped[int]
    swelling: Mapped[int]
    today_score: Mapped[Numeric] = mapped_column(Numeric(3, 1))
    usual_score: Mapped[Numeric | None] = mapped_column(Numeric(3, 1), nullable=True)
    change: Mapped[Numeric | None] = mapped_column(Numeric(3, 1), nullable=True)

    follow_up_answers: Mapped[dict] = mapped_column(JSONB, default=dict)

    version: Mapped[int] = mapped_column(default=1)
    is_current: Mapped[bool] = mapped_column(default=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checkin.id"), nullable=True
    )

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped[Patient] = relationship(back_populates="checkins")

    __table_args__ = (
        CheckConstraint("fatigue BETWEEN 1 AND 10", name="ck_fatigue_range"),
        CheckConstraint("pain BETWEEN 1 AND 10", name="ck_pain_range"),
        CheckConstraint("swelling BETWEEN 1 AND 10", name="ck_swelling_range"),
        # Only one CURRENT check-in per patient per day -- enforced by the
        # database, not just application logic.
        Index(
            "uq_checkin_patient_date_current",
            "patient_id",
            "checkin_date",
            unique=True,
            postgresql_where=(is_current == True),  # noqa: E712
        ),
    )


class CheckinFollowupLog(Base):
    """Audit trail of follow-up-answer amendments to a check-in. Not the
    source of truth (that's `CheckIn.follow_up_answers`) -- exists purely
    so "who answered what, when" is reconstructable even though amending
    follow-ups does not bump `CheckIn.version`.
    """

    __tablename__ = "checkin_followup_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    checkin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkin.id"))
    answers: Mapped[dict] = mapped_column(JSONB)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Flag(Base):
    __tablename__ = "flag"

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    rule_code: Mapped[str] = mapped_column(String(32))
    rule_version: Mapped[str] = mapped_column(String(32))  # int-as-str for DB rules, or "builtin-1"
    level: Mapped[FlagLevel] = mapped_column(flag_level_enum)
    status: Mapped[FlagStatus] = mapped_column(flag_status_enum, default=FlagStatus.OPEN)

    first_fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_count: Mapped[int] = mapped_column(default=1)
    why_snapshot: Mapped[dict] = mapped_column(JSONB)

    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[Patient] = relationship(back_populates="flags")
    events: Mapped[list["FlagEvent"]] = relationship(
        back_populates="flag", order_by="FlagEvent.fired_at", lazy="selectin"
    )
    actions: Mapped[list["CareAction"]] = relationship(
        back_populates="flag", order_by="CareAction.created_at", lazy="selectin"
    )

    __table_args__ = (Index("ix_flag_patient_status_level", "patient_id", "status", "level"),)


class FlagEvent(Base):
    __tablename__ = "flag_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flag.id"))
    checkin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checkin.id"), nullable=True
    )  # NULL for timer-fired rules (R9)
    rule_version: Mapped[str] = mapped_column(String(32))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    numbers_snapshot: Mapped[dict] = mapped_column(JSONB)

    flag: Mapped[Flag] = relationship(back_populates="events")


class CareAction(Base):
    """Acknowledge / log-call / escalate / resolve -- spec section 8.
    `organisation_id` is copied from the acting actor at INSERT time and
    never reconciled afterward (spec section 12, "time and organisation").
    """

    __tablename__ = "care_action"

    id: Mapped[uuid.UUID] = _uuid_pk()
    flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flag.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"))
    action_type: Mapped[CareActionType] = mapped_column(care_action_type_enum)

    minutes: Mapped[int | None] = mapped_column(nullable=True)
    call_type: Mapped[CallType | None] = mapped_column(call_type_enum, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    flag: Mapped[Flag] = relationship(back_populates="actions")

    __table_args__ = (
        CheckConstraint("minutes IS NULL OR minutes >= 0", name="ck_minutes_non_negative"),
    )


class MonthlySummaryCache(Base):
    __tablename__ = "monthly_summary_cache"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)  # first-of-month
    payload: Mapped[dict] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
