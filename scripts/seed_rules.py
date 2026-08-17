"""Idempotently loads the ten rules from app.domain.rules.seed_data
(spec section 5, D3-01..D3-10) into the rule_definition table.

Safe to re-run: existing (rule_code, version) rows are left untouched.

    python -m scripts.seed_rules
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import RuleDefinition
from app.domain.rules.seed_data import RULES


async def seed_rules() -> None:
    async with SessionLocal() as session:
        existing = await session.execute(select(RuleDefinition.rule_code, RuleDefinition.version))
        existing_pairs = {(code, version) for code, version in existing.all()}

        inserted = 0
        for rule in RULES:
            if (rule.rule_code, rule.version) in existing_pairs:
                continue
            session.add(
                RuleDefinition(
                    rule_code=rule.rule_code,
                    version=rule.version,
                    level=rule.level.value,
                    description=rule.description,
                    rule_type=rule.rule_type,
                    params=rule.params,
                    follow_up_questions=list(rule.follow_up_questions),
                    requires_fever_gate=rule.requires_fever_gate,
                    care_manager_action=rule.care_manager_action,
                    is_active=True,
                )
            )
            inserted += 1

        await session.commit()
        print(f"Seeded {inserted} rule version(s); {len(existing_pairs)} already present.")


if __name__ == "__main__":
    asyncio.run(seed_rules())
