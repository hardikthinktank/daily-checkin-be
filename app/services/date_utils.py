from __future__ import annotations

import calendar
from datetime import date


def month_bounds(month: date) -> tuple[date, date, int]:
    """Returns (first_of_month, last_of_month, days_in_month)."""
    first = month.replace(day=1)
    days_in_month = calendar.monthrange(first.year, first.month)[1]
    last = first.replace(day=days_in_month)
    return first, last, days_in_month
