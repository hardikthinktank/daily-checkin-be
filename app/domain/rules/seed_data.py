"""The ten rules from spec section 5, D3-01 through D3-10, as plain
`RuleDefinition` objects.

This is the single source of truth for both the DB seed script
(scripts/seed_rules.py, which writes these into `rule_definition` rows)
and the domain tests (which use them directly, no database involved).
Keep the two in sync by construction -- never hand-duplicate this table
elsewhere.

Every threshold here is a placeholder for the demo (spec's opening
warning and section 12): none of it is clinically validated. Grep for
"demo-placeholder" before any of this fires for a real patient.
"""
from __future__ import annotations

from app.domain.rules.types import FlagLevel, RuleDefinition

SOURCE = "demo-placeholder"

RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        rule_code="D3-01",
        version=1,
        level=FlagLevel.REVIEW,
        description="Pain is 7 or higher.",
        rule_type="threshold_gte",
        params={"field": "pain", "gte": 7},
        follow_up_questions=("days_at_level", "new_joint", "fever"),
        requires_fever_gate=True,
        care_manager_action="Review within one business day.",
    ),
    RuleDefinition(
        rule_code="D3-02",
        version=1,
        level=FlagLevel.REVIEW,
        description="Swelling is 7 or higher.",
        rule_type="threshold_gte",
        params={"field": "swelling", "gte": 7},
        follow_up_questions=("which_joints", "morning_stiffness", "fever"),
        requires_fever_gate=True,
        care_manager_action="Review within one business day.",
    ),
    RuleDefinition(
        rule_code="D3-03",
        version=1,
        level=FlagLevel.REVIEW,
        description="Fatigue is 8 or higher three check-ins in a row.",
        rule_type="streak_gte",
        params={"field": "fatigue", "gte": 8, "days": 3},
        follow_up_questions=("sleep",),
        care_manager_action="Offer a depression screen at next contact.",
    ),
    RuleDefinition(
        rule_code="D3-04",
        version=1,
        level=FlagLevel.URGENT,
        description="Today's score is 3.0 or more above the usual score.",
        rule_type="change_gte",
        params={"gte": 3.0},
        follow_up_questions=("medication",),
        care_manager_action="Call the patient within 24 hours.",
    ),
    RuleDefinition(
        rule_code="D3-05",
        version=1,
        level=FlagLevel.URGENT,
        description="Any of the three answers is 10.",
        rule_type="any_field_gte",
        params={"fields": ["fatigue", "pain", "swelling"], "gte": 10},
        follow_up_questions=("fever",),
        requires_fever_gate=True,
        care_manager_action="Reach out the same day.",
    ),
    RuleDefinition(
        rule_code="D3-06",
        version=1,
        level=FlagLevel.CRITICAL,
        description="Patient answers yes to fever and is on a biologic or similar drug.",
        rule_type="fever_and_biologic",
        params={},
        follow_up_questions=(),
        care_manager_action=(
            "Contact the physician now. Hold the next dose until the physician advises."
        ),
    ),
    RuleDefinition(
        rule_code="D3-07",
        version=1,
        level=FlagLevel.REVIEW,
        description="Morning stiffness over 60 minutes and swelling 6 or higher.",
        rule_type="followup_choice_at_least_and_today_gte",
        params={
            "answer_field": "morning_stiffness",
            "at_least": "over 60 min",
            "today_field": "swelling",
            "today_gte": 6,
        },
        follow_up_questions=(),
        care_manager_action="Document; check against standing orders.",
    ),
    RuleDefinition(
        rule_code="D3-08",
        version=1,
        level=FlagLevel.REVIEW,
        description="Patient says they did not take their medication.",
        rule_type="answer_equals",
        params={"field": "medication", "equals": "no"},
        follow_up_questions=("reason",),
        care_manager_action="Adherence call; record the reason.",
    ),
    RuleDefinition(
        rule_code="D3-09",
        version=1,
        level=FlagLevel.REVIEW,
        description="Three days in a row with no check-in.",
        # Evaluated by app/jobs/no_checkin_timer.py, on a schedule -- it
        # never runs through the submission-triggered engine.evaluate()
        # loop, so this rule_type is intentionally absent from
        # STRATEGY_REGISTRY. It's still a versioned DB row so "why it
        # fired" and "which version was in force" work the same way as
        # every other rule.
        rule_type="no_checkin_streak",
        params={"days": 3},
        follow_up_questions=(),
        care_manager_action="Re-engagement call.",
    ),
    RuleDefinition(
        rule_code="D3-10",
        version=1,
        level=FlagLevel.NOTE,
        description="Seven check-ins in a row at 3.0 or below with nothing open.",
        rule_type="streak_lte_nothing_open",
        params={"field": "today_score", "lte": 3.0, "days": 7},
        follow_up_questions=(),
        care_manager_action="None. Record that the patient is steady.",
    ),
)

# The subset the generic engine.evaluate() loop can run directly. D3-09
# is excluded -- it runs on a timer (see app/jobs/no_checkin_timer.py).
SUBMISSION_RULES: tuple[RuleDefinition, ...] = tuple(r for r in RULES if r.rule_type != "no_checkin_streak")

TIMER_RULES: tuple[RuleDefinition, ...] = tuple(r for r in RULES if r.rule_type == "no_checkin_streak")
