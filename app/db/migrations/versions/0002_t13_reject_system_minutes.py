"""T13: only a human can add minutes. If the system itself tries to
write a minutes entry (a `care_action` row with action_type='log_call'),
the DATABASE must refuse it -- not the API layer. This migration is the
actual mechanism the app-layer role check backs up, not a substitute for
it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION reject_system_minutes() RETURNS trigger AS $$
DECLARE
    acting_actor_type actor_type;
BEGIN
    IF NEW.action_type = 'log_call' THEN
        SELECT actor_type INTO acting_actor_type FROM actor WHERE id = NEW.actor_id;
        IF acting_actor_type = 'system' THEN
            RAISE EXCEPTION
                'system actors may not record care-team minutes (actor_id=%)', NEW.actor_id
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_TRIGGER = """
CREATE TRIGGER trg_reject_system_minutes
    BEFORE INSERT OR UPDATE ON care_action
    FOR EACH ROW EXECUTE FUNCTION reject_system_minutes();
"""

_DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_reject_system_minutes ON care_action;"
_DROP_FUNCTION = "DROP FUNCTION IF EXISTS reject_system_minutes();"


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)
    op.execute(_CREATE_TRIGGER)


def downgrade() -> None:
    op.execute(_DROP_TRIGGER)
    op.execute(_DROP_FUNCTION)
