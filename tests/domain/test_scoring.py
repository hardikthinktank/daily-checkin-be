from decimal import Decimal

import pytest

from app.domain.scoring import score_change, today_score, usual_score


def test_today_score_averages_and_rounds():
    assert today_score(3, 3, 3) == Decimal("3.0")
    assert today_score(8, 4, 4) == Decimal("5.3")  # 16/3 = 5.333... -> 5.3


def test_usual_score_needs_five_prior_checkins():
    assert usual_score([Decimal("3.0"), Decimal("3.0"), Decimal("3.0"), Decimal("3.0")]) is None


def test_usual_score_is_median_of_last_14():
    scores = [Decimal(v) for v in [5, 3, 3, 3, 3, 3]]
    assert usual_score(scores) == Decimal("3.0")


def test_usual_score_only_uses_most_recent_14():
    # 14 recent 3.0s followed by older, very different scores that must
    # not affect the median.
    recent = [Decimal("3.0")] * 14
    older = [Decimal("9.0")] * 10
    assert usual_score(recent + older) == Decimal("3.0")


@pytest.mark.parametrize(
    "today, usual, expected",
    [
        (Decimal("8.0"), Decimal("5.0"), Decimal("3.0")),
        (Decimal("3.0"), None, None),
    ],
)
def test_score_change(today, usual, expected):
    assert score_change(today, usual) == expected
