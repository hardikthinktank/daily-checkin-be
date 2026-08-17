"""Initial schema: drug, patient, actor, rule_definition, checkin,
checkin_followup_log, flag, flag_event, care_action, monthly_summary_cache.

Revision ID: 0001
Revises:
Create Date: 2026-08-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each ENUM type is created exactly once, implicitly, the first time
    # it is used as a column in op.create_table() below (create_type
    # defaults to True). Every other column that reuses the same type
    # name must pass create_type=False -- otherwise SQLAlchemy tries to
    # CREATE TYPE a second time and Postgres rejects it as a duplicate.
    flag_level = postgresql.ENUM(
        "Note", "Review", "Urgent", "Critical", name="flag_level", create_type=True
    )
    flag_level_no_create = postgresql.ENUM(
        "Note", "Review", "Urgent", "Critical", name="flag_level", create_type=False
    )

    flag_status = postgresql.ENUM(
        "open", "acknowledged", "escalated", "resolved", name="flag_status", create_type=True
    )

    actor_type = postgresql.ENUM("human", "system", name="actor_type", create_type=True)

    actor_role = postgresql.ENUM(
        "patient", "care_manager", "physician", "admin", "system", name="actor_role", create_type=True
    )

    care_action_type = postgresql.ENUM(
        "acknowledge", "log_call", "escalate", "resolve", name="care_action_type", create_type=True
    )

    call_type = postgresql.ENUM("phone", "video", "async_message", name="call_type", create_type=True)

    op.create_table(
        "drug",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("is_biologic_or_similar", sa.Boolean, nullable=False),
    )

    op.create_table(
        "patient",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mrn", sa.String(64), nullable=False, unique=True),
        sa.Column("diagnosis", sa.String(200), nullable=False),
        sa.Column("current_drug_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drug.id"), nullable=False),
        sa.Column("enrollment_date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "actor",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("role", actor_role, nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "rule_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_code", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("level", flag_level, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=False),
        sa.Column("follow_up_questions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("requires_fever_gate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("care_manager_action", sa.String(500), nullable=False, server_default=""),
        sa.Column("threshold_source", sa.String(64), nullable=False, server_default="demo-placeholder"),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rule_code", "version", name="uq_rule_code_version"),
    )

    op.create_table(
        "checkin",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient.id"), nullable=False),
        sa.Column("checkin_date", sa.Date, nullable=False),
        sa.Column("client_submission_id", sa.String(128), nullable=False, unique=True),
        sa.Column("fatigue", sa.Integer, nullable=False),
        sa.Column("pain", sa.Integer, nullable=False),
        sa.Column("swelling", sa.Integer, nullable=False),
        sa.Column("today_score", sa.Numeric(3, 1), nullable=False),
        sa.Column("usual_score", sa.Numeric(3, 1), nullable=True),
        sa.Column("change", sa.Numeric(3, 1), nullable=True),
        sa.Column("follow_up_answers", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checkin.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("fatigue BETWEEN 1 AND 10", name="ck_fatigue_range"),
        sa.CheckConstraint("pain BETWEEN 1 AND 10", name="ck_pain_range"),
        sa.CheckConstraint("swelling BETWEEN 1 AND 10", name="ck_swelling_range"),
    )
    op.create_index(
        "uq_checkin_patient_date_current",
        "checkin",
        ["patient_id", "checkin_date"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "checkin_followup_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("checkin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checkin.id"), nullable=False),
        sa.Column("answers", postgresql.JSONB, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "flag",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient.id"), nullable=False),
        sa.Column("rule_code", sa.String(32), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("level", flag_level_no_create, nullable=False),
        sa.Column("status", flag_status, nullable=False, server_default="open"),
        sa.Column("first_fired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("why_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("actor.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flag_patient_status_level", "flag", ["patient_id", "status", "level"])

    op.create_table(
        "flag_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flag.id"), nullable=False),
        sa.Column("checkin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checkin.id"), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("numbers_snapshot", postgresql.JSONB, nullable=False),
    )

    op.create_table(
        "care_action",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flag.id"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("actor.id"), nullable=False),
        sa.Column("action_type", care_action_type, nullable=False),
        sa.Column("minutes", sa.Integer, nullable=True),
        sa.Column("call_type", call_type, nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("note", sa.String(2000), nullable=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("minutes IS NULL OR minutes >= 0", name="ck_minutes_non_negative"),
    )

    op.create_table(
        "monthly_summary_cache",
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient.id"), primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("monthly_summary_cache")
    op.drop_table("care_action")
    op.drop_table("flag_event")
    op.drop_table("flag")
    op.drop_table("checkin_followup_log")
    op.drop_table("checkin")
    op.drop_table("rule_definition")
    op.drop_table("actor")
    op.drop_table("patient")
    op.drop_table("drug")

    bind = op.get_bind()
    for name in ("call_type", "care_action_type", "actor_role", "actor_type", "flag_status", "flag_level"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
