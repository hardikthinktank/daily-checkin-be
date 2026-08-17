"""The rule engine itself: evaluate() runs the full DB-defined rule table
against one day's context. Pure function, no I/O -- see module docstring
in types.py for why.

Called twice per submission by the service layer: once with only the
three base answers, and again after the patient answers any follow-up
questions the first pass asked for (spec section 2, step 4). Calling it
twice is safe -- it's a pure function of `ctx`, and the flag reconciler
(flags.py) is idempotent against the result.
"""
from __future__ import annotations

from app.domain.rules.strategies import STRATEGY_REGISTRY
from app.domain.rules.types import CheckinContext, RuleDefinition, RuleFiring


def evaluate(ctx: CheckinContext, rule_table: list[RuleDefinition]) -> list[RuleFiring]:
    firings: list[RuleFiring] = []
    for rule in rule_table:
        strategy = STRATEGY_REGISTRY[rule.rule_type]
        why = strategy(ctx, rule.params)
        if why is None:
            continue
        asks = rule.follow_up_questions
        if rule.requires_fever_gate and not ctx.history.on_biologic:
            # The fever question only exists for patients on a biologic
            # or similar drug -- spec section 5, closing note. For
            # everyone else the rule that feeds on it does not apply.
            asks = tuple(q for q in asks if q != "fever")
        firings.append(RuleFiring(rule.rule_code, rule.version, rule.level, why, asks))
    return firings


def pending_followups(firings: list[RuleFiring], already_answered: dict[str, str]) -> tuple[str, ...]:
    """Union of follow-up question codes still needed across all firings,
    excluding ones the patient has already answered (or skipped) this
    check-in.
    """
    seen: list[str] = []
    for firing in firings:
        for code in firing.ask:
            if code not in already_answered and code not in seen:
                seen.append(code)
    return tuple(seen)
