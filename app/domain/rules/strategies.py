"""One function per rule *shape*. A `RuleDefinition` row picks a shape via
`rule_type` and supplies its own thresholds via `params` -- so tuning R1's
pain threshold from 7 to 8 is a data edit (a new RuleDefinition version),
not a code change. Adding an eleventh rule that fits an existing shape is
also just a data edit; only a genuinely new shape needs a new function
here.

Every strategy has the signature:

    (ctx: CheckinContext, params: dict) -> dict | None

Returning a dict means the rule fired; the dict is the "why" snapshot
(the exact numbers that satisfied it, spec section 8). Returning None
means it did not fire.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.domain.rules.types import CheckinContext, SKIPPED

FIELD_GETTERS = {
    "fatigue": lambda r: r.fatigue,
    "pain": lambda r: r.pain,
    "swelling": lambda r: r.swelling,
    "today_score": lambda r: r.today_score,
}

# Ordinal ordering for the fixed-choice follow-up answers that a rule's
# threshold might need to compare against (spec section 6 -- these are
# buttons, never free text, so a fixed ordering is exhaustive).
CHOICE_ORDER = {
    "morning_stiffness": ["under 30 min", "30-60 min", "over 60 min"],
    "days_at_level": ["1", "2-3", "4-7", "more than 7"],
}


def _consecutive_days_ending_today(ctx: CheckinContext, count: int):
    """Return [today, ...(count-1) prior records] if they exist and form
    an unbroken run of consecutive calendar days ending today, else None.
    """
    records = [ctx.today, *ctx.history.recent_records]
    if len(records) < count:
        return None
    window = records[:count]
    for newer, older in zip(window, window[1:]):
        if (newer.checkin_date - older.checkin_date) != timedelta(days=1):
            return None
    return window


def threshold_gte(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when a single field on today's submission is >= a threshold.
    Used by R1 (pain), R2 (swelling).
    """
    field_name = params["field"]
    threshold = params["gte"]
    value = FIELD_GETTERS[field_name](ctx.today)
    if value >= threshold:
        return {"field": field_name, "value": value, "gte": threshold}
    return None


def any_field_gte(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when ANY of several fields on today's submission is >= a
    threshold. Used by R5 ("any of the three answers is 10").
    """
    threshold = params["gte"]
    hits = {
        f: FIELD_GETTERS[f](ctx.today)
        for f in params["fields"]
        if FIELD_GETTERS[f](ctx.today) >= threshold
    }
    if hits:
        hits_str = ", ".join(f"{field}: {value}" for field, value in hits.items())
        return {"hits": hits_str, "gte": threshold}
    return None


def streak_gte(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when a field has been >= a threshold for N consecutive days
    ending today. Used by R3 (fatigue >= 8, three days).
    """
    field_name = params["field"]
    threshold = params["gte"]
    days = params["days"]
    window = _consecutive_days_ending_today(ctx, days)
    if window is None:
        return None
    values = [FIELD_GETTERS[field_name](r) for r in window]
    if all(v >= threshold for v in values):
        return {"field": field_name, "values": values, "gte": threshold, "days": days}
    return None


def streak_lte_nothing_open(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when a field has been <= a threshold for N consecutive days
    ending today AND the patient currently has nothing open. Used by R10.

    "Nothing open" excludes Note-level flags -- callers must populate
    `history.open_flag_levels` with only Review/Urgent/Critical levels
    (spec section 8: Notes are recorded but are not work).
    """
    if ctx.history.open_flag_levels:
        return None
    field_name = params["field"]
    threshold = Decimal(str(params["lte"]))
    days = params["days"]
    window = _consecutive_days_ending_today(ctx, days)
    if window is None:
        return None
    values = [FIELD_GETTERS[field_name](r) for r in window]
    if all(v <= threshold for v in values):
        return {"field": field_name, "values": [str(v) for v in values], "lte": str(threshold), "days": days}
    return None


def change_gte(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when today's score is >= usual score + a threshold. Used by
    R4. Must not fire when there is no usual score yet (< 5 prior
    check-ins) -- a brand-new patient must never be told they are
    flaring.
    """
    if ctx.change is None:
        return None
    threshold = Decimal(str(params["gte"]))
    if ctx.change >= threshold:
        return {
            "today_score": str(ctx.today.today_score),
            "usual_score": str(ctx.usual_score),
            "change": str(ctx.change),
            "gte": str(threshold),
        }
    return None


def answer_equals(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when a given follow-up answer equals a fixed value. Used by
    R8 (medication == "no").
    """
    field_name = params["field"]
    expected = params["equals"]
    value = ctx.today.follow_up_answers.get(field_name)
    if value == expected:
        return {"field": field_name, "value": value}
    return None


def fever_and_biologic(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when the patient answered fever=yes AND is on a biologic (or
    similar) drug. Used by R6. This mirrors (deliberately, redundantly)
    the section-7 hardcoded failsafe -- R6 is the *configurable* version;
    the failsafe is the one that still works if this row is ever deleted
    or misconfigured.
    """
    fever_answer = ctx.today.follow_up_answers.get("fever")
    if fever_answer == "yes" and ctx.history.on_biologic:
        return {"fever": "yes", "on_biologic": True}
    return None


def followup_choice_at_least_and_today_gte(ctx: CheckinContext, params: dict) -> dict | None:
    """Fires when a follow-up answer is at or beyond a point in its fixed
    choice list AND a field on today's submission is >= a threshold.
    Used by R7 (morning stiffness over 60 min AND swelling >= 6).

    Only reachable on the SECOND evaluate() pass, once the follow-up
    answer that feeds it has actually been collected (spec section 2,
    step 4) -- on the first pass the answer is absent and this correctly
    returns None.
    """
    answer_field = params["answer_field"]
    order = CHOICE_ORDER[answer_field]
    at_least = params["at_least"]
    today_field = params["today_field"]
    today_threshold = params["today_gte"]

    answer = ctx.today.follow_up_answers.get(answer_field)
    if answer is None or answer == SKIPPED or answer not in order:
        return None
    if order.index(answer) < order.index(at_least):
        return None

    today_value = FIELD_GETTERS[today_field](ctx.today)
    if today_value >= today_threshold:
        return {
            answer_field: answer,
            today_field: today_value,
            "today_gte": today_threshold,
        }
    return None


STRATEGY_REGISTRY = {
    "threshold_gte": threshold_gte,
    "any_field_gte": any_field_gte,
    "streak_gte": streak_gte,
    "streak_lte_nothing_open": streak_lte_nothing_open,
    "change_gte": change_gte,
    "answer_equals": answer_equals,
    "fever_and_biologic": fever_and_biologic,
    "followup_choice_at_least_and_today_gte": followup_choice_at_least_and_today_gte,
}

# The params keys each strategy reads via params["..."]. A RuleDefinition
# saved with a rule_type but the wrong params shape doesn't fail until
# the FIRST TIME it fires -- a bare KeyError, for every patient, at
# submission time. rule_admin_service.create_new_version() checks a new
# version against this before it can ever go active; see
# tests/domain/test_rule_params_validation.py for exactly the incident
# this guards against (an empty/placeholder params body reaching
# threshold_gte, which needs "field" and "gte").
REQUIRED_PARAMS: dict[str, frozenset[str]] = {
    "threshold_gte": frozenset({"field", "gte"}),
    "any_field_gte": frozenset({"fields", "gte"}),
    "streak_gte": frozenset({"field", "gte", "days"}),
    "streak_lte_nothing_open": frozenset({"field", "lte", "days"}),
    "change_gte": frozenset({"gte"}),
    "answer_equals": frozenset({"field", "equals"}),
    "fever_and_biologic": frozenset(),
    "followup_choice_at_least_and_today_gte": frozenset(
        {"answer_field", "at_least", "today_field", "today_gte"}
    ),
    # Not in STRATEGY_REGISTRY (evaluated by jobs/no_checkin_timer.py, not
    # the submission-triggered engine loop) but still a rule_type users
    # can save via the admin endpoint, so it still needs validating.
    "no_checkin_streak": frozenset({"days"}),
}


def missing_params(rule_type: str, params: dict) -> frozenset[str]:
    """Returns the required keys `params` is missing for `rule_type`.
    Empty means `params` is valid for that strategy. Unknown rule_types
    are the caller's problem (checked separately, against
    STRATEGY_REGISTRY / REQUIRED_PARAMS membership).
    """
    required = REQUIRED_PARAMS.get(rule_type, frozenset())
    return required - params.keys()
