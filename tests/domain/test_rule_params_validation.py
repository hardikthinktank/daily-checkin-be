"""Regression coverage for a real incident: POST /admin/rules accepted a
new D3-01 version with params={"additionalProp1": {}} (Swagger UI's
generic placeholder for an empty dict field) instead of the {"field":
..., "gte": ...} threshold_gte actually reads. That version went active
and broke check-in submission for every patient the next time D3-01 was
evaluated -- a bare KeyError('field') deep in the rule engine.

missing_params() is what rule_admin_service.create_new_version() now
checks before a new version can go active at all.
"""
from __future__ import annotations

import pytest

from app.domain.rules.strategies import REQUIRED_PARAMS, STRATEGY_REGISTRY, missing_params
from app.domain.rules.seed_data import RULES


def test_every_registered_strategy_has_a_required_params_entry():
    for rule_type in STRATEGY_REGISTRY:
        assert rule_type in REQUIRED_PARAMS


def test_the_swagger_placeholder_is_rejected_for_threshold_gte():
    missing = missing_params("threshold_gte", {"additionalProp1": {}})
    assert missing == frozenset({"field", "gte"})


def test_empty_params_rejected_for_every_rule_type_that_needs_something():
    for rule_type, required in REQUIRED_PARAMS.items():
        if not required:
            continue  # fever_and_biologic legitimately needs nothing
        assert missing_params(rule_type, {}) == required


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_code)
def test_every_seeded_rule_definition_satisfies_its_own_rule_type(rule):
    """The ten shipped rules must never trip the validator they enforce
    on everyone else.
    """
    assert missing_params(rule.rule_type, rule.params) == frozenset()
