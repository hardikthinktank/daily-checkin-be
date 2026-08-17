""""Why it fired" text, shared by the care manager console (spec section
8) and the monthly summary's flags table (spec section 10.6, "what fired
it") -- one lookup so the two screens can never show different wording
for the same rule_code/rule_version.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuleDefinition
from app.domain.rules.failsafes import FEVER_RULE_CODE, SELF_HARM_RULE_CODE

BUILTIN_DESCRIPTIONS = {
    FEVER_RULE_CODE: "Fever reported by a patient on a biologic or similar drug (built-in protection).",
    SELF_HARM_RULE_CODE: "Positive answer to the self-harm question (built-in protection).",
}
BUILTIN_ACTIONS = {
    FEVER_RULE_CODE: "Contact the physician now. Hold the next dose until the physician advises.",
    SELF_HARM_RULE_CODE: "Contact the physician immediately.",
}


async def describe_rule(session: AsyncSession, rule_code: str, rule_version: str) -> tuple[str, str]:
    """Returns (description, care_manager_action) for a fired rule,
    whether it came from the DB rule table or a built-in failsafe.
    """
    if rule_code in BUILTIN_DESCRIPTIONS:
        return BUILTIN_DESCRIPTIONS[rule_code], BUILTIN_ACTIONS[rule_code]

    # rule_version is not always a real DB version number -- R9 falls
    # back to the literal string "builtin-default" when its rule_definition
    # row is missing (app/jobs/no_checkin_timer.py). That firing still has
    # no row to look up, same as any other version string this table
    # doesn't recognise.
    if not rule_version.isdigit():
        return "(fired using a built-in default; no matching rule_definition row on file)", ""

    rule_row = await session.scalar(
        select(RuleDefinition).where(
            RuleDefinition.rule_code == rule_code,
            RuleDefinition.version == int(rule_version),
        )
    )
    if rule_row is None:
        return "(rule version no longer on file)", ""
    return rule_row.description, rule_row.care_manager_action
