"""Response models for the admin list (spec section 9)."""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.services.admin_list_service import AdminListRow


class DayCellResponse(BaseModel):
    day: int = Field(..., description="Day of the month, 1-31.")
    level: str | None = Field(None, description="Flag level colouring this day, or null if there was no check-in.")


class AdminListRowResponse(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    mrn: str
    diagnosis: str
    therapy: str = Field(..., description="Patient's current drug.")

    month_strip: list[DayCellResponse]
    checkins_done: int
    checkins_expected: int
    checkins_pct: float = Field(..., description="checkins_done / checkins_expected, as a percentage.")
    average_score: float | None = Field(None, description="This month's average D3 score.")
    last_checkin_date: date | None = None
    last_checkin_level: str | None = None
    open_items: int = Field(..., description="Count of flags not yet resolved (any level, including Note).")
    minutes_this_month: int
    live_call_this_month: bool = Field(
        ..., description="True only if a phone/video call was logged this month; messages alone never set this."
    )
    days_of_data_this_month: int
    sixteen_day_marker_met: bool = Field(
        ..., description="Whether 16 separate days of data have been collected this month. NOT a billing signal -- see spec section 9."
    )
    sixteen_day_marker_short_by: int = Field(..., description="0 if met, otherwise how many more days are needed.")

    @classmethod
    def from_row(cls, row: AdminListRow) -> "AdminListRowResponse":
        return cls(
            patient_id=row.patient.id,
            patient_name=row.patient.name,
            mrn=row.patient.mrn,
            diagnosis=row.patient.diagnosis,
            therapy=row.patient.current_drug.name,
            month_strip=[DayCellResponse(day=c.day, level=c.level) for c in row.month_strip],
            checkins_done=row.checkins_done,
            checkins_expected=row.checkins_expected,
            checkins_pct=row.checkins_pct,
            average_score=row.average_score,
            last_checkin_date=row.last_checkin_date,
            last_checkin_level=row.last_checkin_level,
            open_items=row.open_items,
            minutes_this_month=row.minutes_this_month,
            live_call_this_month=row.live_call_this_month,
            days_of_data_this_month=row.days_of_data_this_month,
            sixteen_day_marker_met=row.sixteen_day_marker_met,
            sixteen_day_marker_short_by=row.sixteen_day_marker_short_by,
        )
