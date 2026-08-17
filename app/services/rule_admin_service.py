"""Rule administration (spec section 5): rules are DB rows so they can be
edited and approved without a code release, and so "which version was in
force on a given date" is always reconstructable. Editing never mutates
a version that may already have fired -- it inserts a new version and
closes out the previous one's `effective_to`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuleDefinition
from app.domain.rules.strategies import REQUIRED_PARAMS, STRATEGY_REGISTRY, missing_params
from app.services.errors import DomainError

KNOWN_RULE_TYPES = frozenset({*STRATEGY_REGISTRY.keys(), "no_checkin_streak"})


class UnknownRuleTypeError(DomainError):
    error_code = "unknown_rule_type"
    default_message = "rule_type is not one of the strategies the engine knows how to evaluate."


class InvalidRuleParamsError(DomainError):
    """Raised instead of letting a badly-shaped `params` become the
    active version of a rule -- the failure mode otherwise is a bare
    KeyError inside the rule engine, for every patient, the next time
    this rule_code is evaluated, not at save time.
    """

    error_code = "invalid_rule_params"
    default_message = "params is missing one or more keys this rule_type requires."


async def list_rules(session: AsyncSession, *, active_only: bool = True) -> list[RuleDefinition]:
    stmt = select(RuleDefinition).order_by(RuleDefinition.rule_code, RuleDefinition.version.desc())
    if active_only:
        stmt = stmt.where(RuleDefinition.is_active.is_(True))
    return (await session.execute(stmt)).scalars().all()


async def get_rule(session: AsyncSession, rule_id) -> RuleDefinition | None:
    return await session.get(RuleDefinition, rule_id)


async def create_new_version(
    session: AsyncSession,
    *,
    rule_code: str,
    level: str,
    description: str,
    rule_type: str,
    params: dict,
    follow_up_questions: list[str],
    requires_fever_gate: bool,
    care_manager_action: str,
    threshold_source: str,
) -> RuleDefinition:
    """Creates version N+1 of `rule_code` and closes out the previously
    active version's `effective_to`. If `rule_code` has never existed,
    this creates version 1 (use this for brand-new rules too).
    """
    if rule_type not in KNOWN_RULE_TYPES:
        raise UnknownRuleTypeError(
            detail={"rule_type": rule_type, "known_types": sorted(KNOWN_RULE_TYPES)}
        )

    missing = missing_params(rule_type, params)
    if missing:
        raise InvalidRuleParamsError(
            detail={
                "rule_type": rule_type,
                "missing": sorted(missing),
                "required": sorted(REQUIRED_PARAMS.get(rule_type, ())),
                "received": sorted(params.keys()),
            }
        )

    current = await session.scalar(
        select(RuleDefinition)
        .where(RuleDefinition.rule_code == rule_code, RuleDefinition.is_active.is_(True))
        .order_by(RuleDefinition.version.desc())
        .limit(1)
    )
    now = datetime.now(timezone.utc)
    next_version = (current.version + 1) if current else 1

    if current is not None:
        current.is_active = False
        current.effective_to = now

    new_row = RuleDefinition(
        rule_code=rule_code,
        version=next_version,
        level=level,
        description=description,
        rule_type=rule_type,
        params=params,
        follow_up_questions=follow_up_questions,
        requires_fever_gate=requires_fever_gate,
        care_manager_action=care_manager_action,
        threshold_source=threshold_source,
        effective_from=now,
        is_active=True,
    )
    session.add(new_row)
    await session.commit()
    await session.refresh(new_row)
    return new_row
