"""T9 and the general repeat-firing rules from spec section 8."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.rules.engine import evaluate
from app.domain.rules.flags import OpenFlagView, reconcile
from app.domain.rules.seed_data import SUBMISSION_RULES
from app.domain.rules.types import FlagLevel, RuleFiring
from tests.domain.conftest import make_context

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_t9_repeat_pain_firing_within_72h_adds_event_not_a_second_flag():
    existing = OpenFlagView(
        flag_id="flag-1",
        rule_code="D3-01",
        level=FlagLevel.REVIEW,
        last_fired_at=NOW - timedelta(hours=2),
    )
    ctx = make_context(fatigue=5, pain=8, swelling=5, on_biologic=True, prior_scores=None)
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert [f.rule_code for f in firings] == ["D3-01"]

    intents = reconcile(firings, open_flags=[existing], now=NOW)
    assert len(intents) == 1
    assert intents[0].kind == "add_event"
    assert intents[0].existing_flag_id == "flag-1"
    assert intents[0].raise_to_level is None


def test_five_consecutive_days_of_high_pain_stay_one_flag():
    """Simulates five sequential submissions: each reconcile() call sees
    the open-flag state left by the previous one and must keep adding to
    it, never spawning a second flag.
    """
    open_flags: list[OpenFlagView] = []
    last_fired = NOW
    flag_id = None

    for day in range(5):
        firing = RuleFiring("D3-01", 1, FlagLevel.REVIEW, why={"day": day}, ask=())
        intents = reconcile([firing], open_flags=open_flags, now=last_fired)
        assert len(intents) == 1
        if day == 0:
            assert intents[0].kind == "create"
            flag_id = "flag-1"
        else:
            assert intents[0].kind == "add_event"
            assert intents[0].existing_flag_id == flag_id

        last_fired = last_fired + timedelta(days=1)
        open_flags = [
            OpenFlagView(flag_id=flag_id, rule_code="D3-01", level=FlagLevel.REVIEW, last_fired_at=last_fired)
        ]


def test_repeat_at_higher_level_raises_the_open_flag_level():
    existing = OpenFlagView(
        flag_id="flag-1", rule_code="D3-04", level=FlagLevel.URGENT, last_fired_at=NOW - timedelta(hours=1)
    )
    firing = RuleFiring("D3-04", 1, FlagLevel.CRITICAL, why={}, ask=())
    intents = reconcile([firing], open_flags=[existing], now=NOW)
    assert intents[0].kind == "add_event"
    assert intents[0].raise_to_level == FlagLevel.CRITICAL


def test_repeat_at_lower_level_never_lowers_the_open_flag():
    existing = OpenFlagView(
        flag_id="flag-1", rule_code="D3-04", level=FlagLevel.CRITICAL, last_fired_at=NOW - timedelta(hours=1)
    )
    firing = RuleFiring("D3-04", 1, FlagLevel.URGENT, why={}, ask=())
    intents = reconcile([firing], open_flags=[existing], now=NOW)
    assert intents[0].kind == "add_event"
    assert intents[0].raise_to_level is None  # never lowered


def test_firing_after_72h_creates_a_new_flag_instead_of_reusing_the_old_one():
    existing = OpenFlagView(
        flag_id="flag-1", rule_code="D3-01", level=FlagLevel.REVIEW, last_fired_at=NOW - timedelta(hours=73)
    )
    firing = RuleFiring("D3-01", 1, FlagLevel.REVIEW, why={}, ask=())
    intents = reconcile([firing], open_flags=[existing], now=NOW)
    assert intents[0].kind == "create"


def test_unrelated_open_flag_does_not_absorb_a_different_rules_firing():
    existing = OpenFlagView(
        flag_id="flag-1", rule_code="D3-02", level=FlagLevel.REVIEW, last_fired_at=NOW - timedelta(hours=1)
    )
    firing = RuleFiring("D3-01", 1, FlagLevel.REVIEW, why={}, ask=())
    intents = reconcile([firing], open_flags=[existing], now=NOW)
    assert intents[0].kind == "create"
