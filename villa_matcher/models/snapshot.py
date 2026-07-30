"""Snapshot and OccupancyTimeline models."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class OccupancyRecord:
    """A single occupancy entry with confidence classification."""

    villa_name: str
    start_date: date
    end_date: date
    confidence: str  # "confirmed" | "likely_active" | "ambiguous" | "deleted"
    evidence: str = ""  # Human-readable explanation
    opportunity_name: str = ""
    lead_passenger: str = ""
    extras: str = ""

    @property
    def is_blocking(self) -> bool:
        """Records that block availability."""
        return self.confidence in ("confirmed", "likely_active")

    @property
    def is_uncertain(self) -> bool:
        """Records with uncertain status."""
        return self.confidence == "ambiguous"

    def overlaps(self, range_start: date, range_end: date) -> bool:
        """Check overlap with a date range."""
        return self.start_date < range_end and self.end_date > range_start


@dataclass
class OccupancyTimeline:
    """Per-villa timeline of occupancy records sorted by start_date."""

    villa_name: str
    records: list[OccupancyRecord] = field(default_factory=list)

    def __post_init__(self):
        self._sort()

    def _sort(self):
        self.records.sort(key=lambda r: r.start_date)

    def add(self, record: OccupancyRecord):
        self.records.append(record)
        self._sort()

    def get_blocking_records(
        self, range_start: date, range_end: date
    ) -> list[OccupancyRecord]:
        """Return blocking records overlapping the given date range."""
        return [
            r
            for r in self.records
            if r.is_blocking and r.overlaps(range_start, range_end)
        ]

    def get_ambiguous_records(
        self, range_start: date, range_end: date
    ) -> list[OccupancyRecord]:
        """Return ambiguous records overlapping the given date range."""
        return [
            r
            for r in self.records
            if r.is_uncertain and r.overlaps(range_start, range_end)
        ]

    def is_available(
        self, range_start: date, range_end: date
    ) -> tuple[bool, str, list[OccupancyRecord]]:
        """
        Check availability for a date range.

        Returns:
            (is_available, reason, ambiguous_records)
        """
        blocking = self.get_blocking_records(range_start, range_end)
        ambiguous = self.get_ambiguous_records(range_start, range_end)

        if blocking:
            names = ", ".join(r.lead_passenger or r.opportunity_name[:20] for r in blocking)
            return False, f"Blocked by: {names}", ambiguous

        if ambiguous:
            names = ", ".join(r.lead_passenger or r.opportunity_name[:20] for r in ambiguous)
            return True, f"Available but flagged: {names}", ambiguous

        return True, "Available", []

    def is_available_strict(
        self, range_start: date, range_end: date
    ) -> bool:
        """Strict availability: only confirmed/likely_active block."""
        return len(self.get_blocking_records(range_start, range_end)) == 0
