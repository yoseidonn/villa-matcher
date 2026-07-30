"""Date parsing utilities — ported and unified from Resital Villa Scripts.

Handles the various date formats found in Resort Report Excel exports:
- 'DD/MM/YY' string
- 'DD/MM/YYYY' string
- pandas Timestamp
- Python datetime
"""

from datetime import date, datetime

import pandas as pd


def parse_date(value) -> date | None:
    """Parse a date value from any supported format into a date object.

    Returns None if parsing fails or the value is null/NaN.
    """
    if value is None:
        return None
    if pd.isna(value):
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, pd.Timestamp):
        return value.date()

    # Try string formats
    raw = str(value).strip()
    if not raw:
        return None

    formats = [
        "%d/%m/%y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y",
        "%d.%m.%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def parse_date_strict(value, label: str = "date") -> date:
    """Parse a date value, raising ValueError on failure."""
    result = parse_date(value)
    if result is None:
        raise ValueError(f"Could not parse {label}: {value!r}")
    return result


def format_date(d: date, fmt: str = "%d/%m/%y") -> str:
    """Format a date object as a string."""
    return d.strftime(fmt)


def date_range(start: date, end: date):
    """Yield each date from start (inclusive) to end (exclusive)."""
    from datetime import timedelta

    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples between two dates."""
    months = set()
    current = start
    while current < end:
        months.add((current.year, current.month))
        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)
    return sorted(months)


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given month."""
    import calendar

    return calendar.monthrange(year, month)[1]
