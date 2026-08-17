"""Response models for the monthly physician summary (spec section 10)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class SummaryHeader(BaseModel):
    patient_id: str
    patient_name: str
    month: date
    drug: str
    days_reported: int
    days_in_month: int


class SymptomPoint(BaseModel):
    date: date
    fatigue: int
    pain: int
    swelling: int


class ScorePoint(BaseModel):
    date: date
    today_score: float
    usual_score: float | None


class ScoreChart(BaseModel):
    series: list[ScorePoint]
    usual_score_line: float | None = Field(None, description="Dashed line at the patient's usual score.")
    usual_plus_3_line: float | None = Field(None, description="Second dashed line, 3 points above the usual score.")


class MonthStripDay(BaseModel):
    day: int
    level: str | None = Field(None, description="Null where no check-in came in.")


class FlagsTableRow(BaseModel):
    rule_code: str
    rule_version: str
    what_fired_it: str = Field(..., description='The rule\'s description sentence, e.g. "Pain is 7 or higher."')
    level: str
    first_fired_at: datetime
    event_count: int
    status: str
    minutes: int = Field(..., description="Care-team minutes logged against this flag this month.")


class TeamActionRow(BaseModel):
    date: datetime
    action_type: str
    minutes: int | None = None
    call_type: str | None = None
    reason: str | None = None
    note: str | None = None


class RecordFacts(BaseModel):
    days_of_data: int
    sixteen_day_marker_met: bool
    sixteen_day_marker_short_by: int
    live_call_happened: bool
    minutes_recorded: int


class MonthlySummaryResponse(BaseModel):
    header: SummaryHeader
    symptom_chart: list[SymptomPoint]
    score_chart: ScoreChart
    days_by_level: dict[str, int] = Field(
        ...,
        description='Count of days landing at each level this month. Keys: "none", "Note", "Review", "Urgent", "Critical".',
    )
    month_strip: list[MonthStripDay]
    flags_table: list[FlagsTableRow]
    team_actions: list[TeamActionRow] = Field(..., description="Every call, escalation, and resolution, in date order.")
    record_facts: RecordFacts
