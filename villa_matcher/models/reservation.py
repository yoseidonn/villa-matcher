"""Reservation model."""

from dataclasses import dataclass
from datetime import date


@dataclass
class Reservation:
    """A single reservation from a report snapshot."""

    opportunity_name: str  # Unique ID across all snapshots
    villa_name: str
    start_date: date  # Holiday Start Date (check-in)
    end_date: date  # Holiday End Date (check-out, exclusive)
    lead_passenger: str = ""
    extras: str = ""
    snapshot_date: date | None = None  # Date of the snapshot/report this came from

    @property
    def duration_days(self) -> int:
        """Duration of the stay in days."""
        return (self.end_date - self.start_date).days

    def overlaps(self, range_start: date, range_end: date) -> bool:
        """Check if this reservation overlaps with the given date range.

        Overlap: reservation.start < range_end AND reservation.end > range_start
        """
        return self.start_date < range_end and self.end_date > range_start

    def __hash__(self) -> int:
        return hash((self.opportunity_name, self.villa_name, self.start_date, self.end_date))
