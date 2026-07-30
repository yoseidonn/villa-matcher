"""Calendar grid rendering utilities.

Produces month-grid data structures that can be consumed by the terminal
UI (rich) or exported to other formats.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from villa_matcher.models.snapshot import OccupancyRecord, OccupancyTimeline


@dataclass
class CalendarDay:
    """A single day cell in the calendar grid."""

    day: int  # 1-31, or 0 for padding
    date_obj: date | None = None
    is_padding: bool = False
    is_today: bool = False
    is_past: bool = False
    occupancy: list[OccupancyRecord] = field(default_factory=list)

    # Turnover detection: same-day checkout + checkin
    is_turnover: bool = False
    has_checkin: bool = False     # this day is someone's arrival
    has_checkout: bool = False    # this day is someone's departure
    checkout_confidence: str = ""
    checkin_confidence: str = ""
    checkout_passenger: str = ""
    checkin_passenger: str = ""

    @property
    def status(self) -> str:
        """Highest-priority status for display."""
        if self.is_padding:
            return "empty"
        if not self.occupancy:
            return "free"
        # Highest confidence determines display
        confidences = [r.confidence for r in self.occupancy]
        if "deleted" in confidences:
            confidences = [c for c in confidences if c != "deleted"]
            if not confidences:
                return "free"

        if "confirmed" in confidences:
            return "confirmed"
        if "likely_active" in confidences:
            return "likely_active"
        if "ambiguous" in confidences:
            return "ambiguous"
        return "free"

    @property
    def label(self) -> str:
        """Short label for the cell (passenger name or status)."""
        if self.is_padding:
            return ""
        if self.occupancy:
            # Show first named passenger
            for r in self.occupancy:
                if r.lead_passenger:
                    return r.lead_passenger[:10]
        return ""

    @property
    def style(self) -> str:
        """Rich/textual style name."""
        return {
            "confirmed": "green",
            "likely_active": "yellow",
            "ambiguous": "red",
            "free": "dim",
            "empty": "dim",
        }.get(self.status, "dim")


@dataclass
class CalendarMonth:
    """A complete month grid with occupancy data."""

    year: int
    month: int
    villa_name: str
    weeks: list[list[CalendarDay]] = field(default_factory=list)
    month_name: str = ""

    def __post_init__(self):
        self.month_name = calendar.month_name[self.month]


def build_month_grid(
    villa_name: str,
    year: int,
    month: int,
    timeline: OccupancyTimeline | None,
    today: date | None = None,
) -> CalendarMonth:
    """Build a CalendarMonth grid for a specific villa and month.

    Args:
        villa_name: Villa for the header.
        year, month: Target month.
        timeline: Occupancy data (None = no bookings).
        today: Reference date for "today" marker.

    Returns:
        CalendarMonth with weeks of CalendarDay cells.
    """
    if today is None:
        today = date.today()

    # Build day→records + checkin/checkout/turnover tracking
    day_records: dict[date, list[OccupancyRecord]] = defaultdict(list)
    day_checkins: dict[date, list[OccupancyRecord]] = defaultdict(list)
    day_checkouts: dict[date, list[OccupancyRecord]] = defaultdict(list)

    if timeline:
        num_days = calendar.monthrange(year, month)[1]
        month_start = date(year, month, 1)
        month_end = date(year, month, num_days)

        for record in timeline.records:
            if record.confidence == "deleted":
                continue

            # Fill occupancy for each day of the stay: [start, end)
            rec_start = max(record.start_date, month_start)
            rec_end = min(record.end_date, month_end + timedelta(days=1))
            d = rec_start
            while d < rec_end:
                if month_start <= d <= month_end:
                    day_records[d].append(record)
                d += timedelta(days=1)

            # Track check-in day (start_date)
            if month_start <= record.start_date <= month_end:
                day_checkins[record.start_date].append(record)

            # Track check-out day (end_date — departure day, villa frees up)
            if month_start <= record.end_date <= month_end:
                day_checkouts[record.end_date].append(record)

    # Build the week grid
    cal = calendar.Calendar(firstweekday=0)  # Monday
    month_days = list(cal.itermonthdates(year, month))

    weeks = []
    current_week = []

    for d in month_days:
        if d.month != month:
            current_week.append(
                CalendarDay(
                    day=d.day,
                    date_obj=d,
                    is_padding=True,
                    is_past=d < today,
                )
            )
        else:
            records = day_records.get(d, [])
            checkins = day_checkins.get(d, [])
            checkouts = day_checkouts.get(d, [])

            # Determine turnover: checkout + checkin on same day
            is_turnover = bool(checkouts and checkins)
            checkout_conf = checkouts[0].confidence if checkouts else ""
            checkin_conf = checkins[0].confidence if checkins else ""
            checkout_pax = checkouts[0].lead_passenger if checkouts else ""
            checkin_pax = checkins[0].lead_passenger if checkins else ""

            # Determine if this day is a checkin or checkout for display
            has_checkin = bool(checkins) and not is_turnover
            has_checkout = bool(checkouts) and not is_turnover

            current_week.append(
                CalendarDay(
                    day=d.day,
                    date_obj=d,
                    is_padding=False,
                    is_today=(d == today),
                    is_past=(d < today),
                    occupancy=records,
                    is_turnover=is_turnover,
                    has_checkin=has_checkin,
                    has_checkout=has_checkout,
                    checkout_confidence=checkout_conf,
                    checkin_confidence=checkin_conf,
                    checkout_passenger=checkout_pax,
                    checkin_passenger=checkin_pax,
                )
            )

        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []

    # Handle any remaining days (shouldn't happen with itermonthdates but being safe)
    if current_week:
        while len(current_week) < 7:
            current_week.append(
                CalendarDay(day=0, is_padding=True)
            )
        weeks.append(current_week)

    return CalendarMonth(
        year=year,
        month=month,
        villa_name=villa_name,
        weeks=weeks,
    )


def get_navigation_months(
    year: int, month: int
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Get (prev_year, prev_month), (next_year, next_month)."""
    if month == 1:
        prev_month = (year - 1, 12)
    else:
        prev_month = (year, month - 1)

    if month == 12:
        next_month = (year + 1, 1)
    else:
        next_month = (year, month + 1)

    return prev_month, next_month
