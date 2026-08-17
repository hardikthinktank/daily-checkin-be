"""Automated versions of spec section 11's test table, T1-T10 and T12
(T11 is an idempotency/DB concern, T13-T15 are DB/API concerns -- see
tests/api/). Run against the rule engine alone: no screens, no database.

"On a biologic" is abbreviated "on drug", matching the spec's own
convention, to keep these readable next to the source table.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.rules.engine import evaluate
from app.domain.rules.failsafes import FEVER_RULE_CODE, check_failsafes
from app.domain.rules.seed_data import SUBMISSION_RULES
from app.domain.rules.types import FlagLevel
from tests.domain.conftest import consecutive_days_before, make_context, make_record, TODAY


def _levels(firings):
    return {f.rule_code: f.level for f in firings}


def _day_level(firings, failsafe_firings=()):
    all_levels = [f.level for f in [*firings, *failsafe_firings]]
    return max(all_levels) if all_levels else None


def _usual_3_0(n=14):
    return [Decimal("3.0")] * n


# ---------------------------------------------------------------- T1 ----
def test_t1_on_drug_usual_3_0_submit_3_3_3_no_rules_fire():
    ctx = make_context(fatigue=3, pain=3, swelling=3, on_biologic=True, prior_scores=_usual_3_0())
    firings = evaluate(ctx, SUBMISSION_RULES)
    failsafes = check_failsafes(ctx)
    assert firings == []
    assert failsafes == []


# ---------------------------------------------------------------- T2 ----
def test_t2_on_drug_usual_3_0_submit_5_8_4_review_r1_asks_fever():
    ctx = make_context(fatigue=5, pain=8, swelling=4, on_biologic=True, prior_scores=_usual_3_0())
    firings = evaluate(ctx, SUBMISSION_RULES)
    levels = _levels(firings)
    assert levels == {"D3-01": FlagLevel.REVIEW}
    r1 = firings[0]
    assert set(r1.ask) == {"days_at_level", "new_joint", "fever"}


# ---------------------------------------------------------------- T3 ----
def test_t3_not_on_drug_usual_3_0_submit_5_8_4_review_r1_fever_not_asked():
    ctx = make_context(fatigue=5, pain=8, swelling=4, on_biologic=False, prior_scores=_usual_3_0())
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert _levels(firings) == {"D3-01": FlagLevel.REVIEW}
    r1 = firings[0]
    assert "fever" not in r1.ask
    assert set(r1.ask) == {"days_at_level", "new_joint"}


# ---------------------------------------------------------------- T4 ----
def test_t4_on_drug_usual_3_0_submit_7_8_8_urgent_r1_r2_r4():
    ctx = make_context(fatigue=7, pain=8, swelling=8, on_biologic=True, prior_scores=_usual_3_0())
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert _levels(firings) == {
        "D3-01": FlagLevel.REVIEW,
        "D3-02": FlagLevel.REVIEW,
        "D3-04": FlagLevel.URGENT,
    }
    assert _day_level(firings) == FlagLevel.URGENT


# ---------------------------------------------------------------- T5 ----
def test_t5_continue_t4_answer_fever_yes_critical_r6_added():
    ctx = make_context(
        fatigue=7,
        pain=8,
        swelling=8,
        on_biologic=True,
        prior_scores=_usual_3_0(),
        follow_up_answers={"fever": "yes"},
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    levels = _levels(firings)
    assert levels["D3-06"] == FlagLevel.CRITICAL
    assert _day_level(firings) == FlagLevel.CRITICAL
    # The failsafe must not double-fire when the DB rule already covered it.
    failsafes = check_failsafes(ctx, already_fired_rule_codes=frozenset(levels))
    assert failsafes == []


# ---------------------------------------------------------------- T6 ----
def test_t6_not_on_drug_same_as_t4_fever_yes_urgent_unchanged_r6_does_not_fire():
    ctx = make_context(
        fatigue=7,
        pain=8,
        swelling=8,
        on_biologic=False,
        prior_scores=_usual_3_0(),
        follow_up_answers={"fever": "yes"},
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    levels = _levels(firings)
    assert "D3-06" not in levels
    assert _day_level(firings) == FlagLevel.URGENT
    failsafes = check_failsafes(ctx, already_fired_rule_codes=frozenset(levels))
    assert failsafes == []


# ---------------------------------------------------------------- T7 ----
def test_t7_rule_table_emptied_fever_yes_critical_from_builtin_protection_alone():
    """Required test per spec section 7: if this fails, the build does
    not ship. Do not weaken, skip, or delete this test.
    """
    ctx = make_context(
        fatigue=7,
        pain=8,
        swelling=8,
        on_biologic=True,
        prior_scores=_usual_3_0(),
        follow_up_answers={"fever": "yes"},
    )
    firings = evaluate(ctx, rule_table=[])  # rule table completely empty
    assert firings == []

    failsafes = check_failsafes(ctx, already_fired_rule_codes=frozenset())
    assert len(failsafes) == 1
    assert failsafes[0].rule_code == FEVER_RULE_CODE
    assert failsafes[0].level == FlagLevel.CRITICAL


# ---------------------------------------------------------------- T8 ----
def test_t8_only_3_days_history_submit_8_8_8_review_r1_r2_only_no_r4_without_usual_score():
    ctx = make_context(
        fatigue=8,
        pain=8,
        swelling=8,
        on_biologic=True,
        prior_scores=[Decimal("3.0"), Decimal("3.0"), Decimal("3.0")],  # only 3, < 5 required
        recent_records=(
            make_record(consecutive_days_before(TODAY, 3)[0], fatigue=3, pain=3, swelling=3),
            make_record(consecutive_days_before(TODAY, 3)[1], fatigue=3, pain=3, swelling=3),
            make_record(consecutive_days_before(TODAY, 3)[2], fatigue=3, pain=3, swelling=3),
        ),
    )
    assert ctx.usual_score is None
    assert ctx.change is None
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert _levels(firings) == {"D3-01": FlagLevel.REVIEW, "D3-02": FlagLevel.REVIEW}


# ---------------------------------------------------------------- T9 ----
# T9 (repeat-firing dedup -> one flag, event count 2) exercises
# domain/rules/flags.py, not evaluate() -- see test_flags_reconcile.py.


# --------------------------------------------------------------- T10 ----
def test_t10_fatigue_8_two_prior_days_submit_8_4_4_review_r3_asks_sleep():
    prior_dates = consecutive_days_before(TODAY, 2)
    ctx = make_context(
        fatigue=8,
        pain=4,
        swelling=4,
        on_biologic=True,
        prior_scores=None,
        recent_records=(
            make_record(prior_dates[0], fatigue=8, pain=2, swelling=2),
            make_record(prior_dates[1], fatigue=8, pain=2, swelling=2),
        ),
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert _levels(firings) == {"D3-03": FlagLevel.REVIEW}
    assert firings[0].ask == ("sleep",)


# --------------------------------------------------------------- T11 ----
# T11 (duplicate submission ID) is an idempotency/persistence concern --
# see tests/api/test_checkins_idempotency.py.


# --------------------------------------------------------------- T12 ----
def test_t12_seven_straight_days_at_3_0_or_below_submit_2_3_3_note_r10():
    prior_dates = consecutive_days_before(TODAY, 6)
    ctx = make_context(
        fatigue=2,
        pain=3,
        swelling=3,
        on_biologic=True,
        prior_scores=None,
        recent_records=tuple(
            make_record(d, fatigue=3, pain=3, swelling=3) for d in prior_dates
        ),
        open_flag_levels=frozenset(),
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert _levels(firings) == {"D3-10": FlagLevel.NOTE}


def test_t12_variant_does_not_fire_if_something_is_open():
    prior_dates = consecutive_days_before(TODAY, 6)
    ctx = make_context(
        fatigue=2,
        pain=3,
        swelling=3,
        on_biologic=True,
        prior_scores=None,
        recent_records=tuple(
            make_record(d, fatigue=3, pain=3, swelling=3) for d in prior_dates
        ),
        open_flag_levels=frozenset({FlagLevel.REVIEW}),
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert "D3-10" not in _levels(firings)


# --------------------------------------------------------- R7 (extra) ---
def test_r7_only_fires_once_the_stiffness_followup_answer_is_present():
    """R7 depends on an answer collected by R2's follow-up -- it must not
    fire on the first evaluate() pass and must fire on the second, once
    the patient has answered (spec section 2, step 4).
    """
    base = dict(fatigue=3, pain=3, swelling=7, on_biologic=True, prior_scores=_usual_3_0())

    first_pass = make_context(**base)
    firings_1 = evaluate(first_pass, SUBMISSION_RULES)
    assert "D3-07" not in _levels(firings_1)

    second_pass = make_context(**base, follow_up_answers={"morning_stiffness": "over 60 min"})
    firings_2 = evaluate(second_pass, SUBMISSION_RULES)
    assert _levels(firings_2)["D3-07"] == FlagLevel.REVIEW


@pytest.mark.parametrize("stiffness", ["under 30 min", "30-60 min"])
def test_r7_does_not_fire_below_the_stiffness_threshold(stiffness):
    ctx = make_context(
        fatigue=3,
        pain=3,
        swelling=7,
        on_biologic=True,
        prior_scores=_usual_3_0(),
        follow_up_answers={"morning_stiffness": stiffness},
    )
    firings = evaluate(ctx, SUBMISSION_RULES)
    assert "D3-07" not in _levels(firings)
