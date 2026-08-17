"""Spec section 4 / section 12 ("the name"): the score is the D3 score.
It is not RAPID3, DAS28, or CDAI -- those are established clinical
measures with specific published formulas, two of which require a doctor
to count swollen joints in person. Any schema, field, or export that
implies otherwise is a bug, not a wording choice.

This is a cheap static guard, not a rule-engine test -- it only imports
schemas/models (no live DB connection is made by importing them), so it
lives at the top level rather than under tests/domain or tests/api.
"""
from __future__ import annotations

import re

import pytest

from app.schemas.checkins import CheckinResponse
from app.schemas.summary import RecordFacts, ScoreChart, ScorePoint, SummaryHeader

FORBIDDEN = re.compile(r"rapid[\s-]?3|das[\s-]?28|\bcdai\b", re.IGNORECASE)

SCHEMAS_TO_CHECK = [CheckinResponse, ScorePoint, ScoreChart, SummaryHeader, RecordFacts]


@pytest.mark.parametrize("schema", SCHEMAS_TO_CHECK, ids=lambda s: s.__name__)
def test_no_schema_field_name_or_description_implies_an_established_measure(schema):
    for field_name, field in schema.model_fields.items():
        assert not FORBIDDEN.search(field_name), f"{schema.__name__}.{field_name} name looks like an established measure"
        text = " ".join(filter(None, [field.description, field.title]))
        assert not FORBIDDEN.search(text), f"{schema.__name__}.{field_name} description/title mentions a real measure"


def test_score_fields_are_named_today_score_and_usual_score_not_renamed():
    assert "today_score" in CheckinResponse.model_fields
    assert "usual_score" in CheckinResponse.model_fields
    assert "today_score" in ScorePoint.model_fields
    assert "usual_score" in ScorePoint.model_fields
