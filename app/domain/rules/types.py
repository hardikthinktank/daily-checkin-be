"""Plain data structures for the rule engine.

Nothing in this module (or the rest of `app.domain`) may import SQLAlchemy,
FastAPI, or touch a database session. The engine has to be runnable with
hand-built Python objects alone -- that is what makes the T1-T12 test cases
from the spec fast, deterministic unit tests instead of integration tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class FlagLevel(str, Enum):
    """Lowest to highest. Comparisons rely on this declaration order."""

    NOTE = "Note"
    REVIEW = "Review"
    URGENT = "Urgent"
    CRITICAL = "Critical"

    @property
    def rank(self) -> int:
        return list(FlagLevel).index(self)

    def __gt__(self, other: "FlagLevel") -> bool:
        return self.rank > other.rank

    def __lt__(self, other: "FlagLevel") -> bool:
        return self.rank < other.rank


# Answer vocabulary for the follow-up questions (section 6 of the spec).
# No free text anywhere -- every answer is one of these fixed choices, or
# the literal string "skipped" when the patient declines to answer.
SKIPPED = "skipped"

# The eight follow-up question codes a rule can ask for (spec section 6).
# Used to validate RuleDefinition.follow_up_questions at save time -- a
# typo'd code here would silently create a "phantom" required follow-up
# the patient app has no matching field for and can never answer.
FOLLOWUP_QUESTION_CODES = frozenset(
    {
        "days_at_level",
        "new_joint",
        "which_joints",
        "morning_stiffness",
        "sleep",
        "medication",
        "reason",
        "fever",
    }
)


@dataclass(frozen=True)
class DailyRecord:
    """One day's worth of data for a patient, as needed by streak rules."""

    checkin_date: date
    fatigue: int
    pain: int
    swelling: int
    today_score: Decimal
    follow_up_answers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PatientHistory:
    """Everything about the patient's recent record a rule might need,
    other than today's own submission.
    """

    on_biologic: bool
    open_flag_levels: frozenset[FlagLevel]
    # Most-recent-first, NOT including today. Callers should supply enough
    # (>= 14) for every streak rule; the engine never queries a database.
    recent_records: tuple[DailyRecord, ...] = ()


@dataclass(frozen=True)
class CheckinContext:
    """Everything evaluate() needs to score one day's submission."""

    today: DailyRecord
    usual_score: Decimal | None
    change: Decimal | None
    history: PatientHistory


@dataclass(frozen=True)
class RuleDefinition:
    """In-memory mirror of one row (one version) of the `rule_definition`
    table. The DB-backed adapter builds these from ORM rows; tests build
    them by hand.
    """

    rule_code: str
    version: int
    level: FlagLevel
    description: str
    rule_type: str
    params: dict
    follow_up_questions: tuple[str, ...] = ()
    requires_fever_gate: bool = False
    care_manager_action: str = ""


@dataclass(frozen=True)
class RuleFiring:
    """One rule firing for one day. `why` holds the exact numbers that
    satisfied the rule -- required by section 8 ("a care manager must
    never see a flag whose cause they cannot inspect").
    """

    rule_code: str
    rule_version: int | str
    level: FlagLevel
    why: dict
    ask: tuple[str, ...] = ()
