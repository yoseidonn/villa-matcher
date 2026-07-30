"""Single-villa availability matcher.

Finds villas available for an entire date range, filtered by capacity
and optionally by location and attributes.
"""

from dataclasses import dataclass, field
from datetime import date

from villa_matcher.models.snapshot import OccupancyTimeline
from villa_matcher.models.villa import Villa, VillaRegistry


@dataclass
class VillaAvailability:
    """Result for a single villa's availability check."""

    villa: Villa
    is_available: bool
    is_flagged: bool  # Available but has ambiguous/uncertain records
    blocking_records: list = field(default_factory=list)
    ambiguous_records: list = field(default_factory=list)
    reason: str = ""

    @property
    def status(self) -> str:
        if not self.is_available:
            return "unavailable"
        if self.is_flagged:
            return "available (flagged)"
        return "available"


def check_villa_availability(
    villa: Villa,
    timeline: OccupancyTimeline | None,
    check_in: date,
    check_out: date,
) -> VillaAvailability:
    """Check if a single villa is available for a date range.

    Args:
        villa: Villa metadata.
        timeline: Occupancy timeline for this villa (None = no known bookings).
        check_in: Desired check-in date.
        check_out: Desired check-out date (exclusive).

    Returns:
        VillaAvailability with status and details.
    """
    if timeline is None:
        return VillaAvailability(
            villa=villa,
            is_available=True,
            is_flagged=False,
            reason="No occupancy data — assumed available.",
        )

    is_avail, reason, ambiguous = timeline.is_available(check_in, check_out)
    blocking = timeline.get_blocking_records(check_in, check_out)

    return VillaAvailability(
        villa=villa,
        is_available=is_avail,
        is_flagged=len(ambiguous) > 0,
        blocking_records=blocking,
        ambiguous_records=ambiguous,
        reason=reason,
    )


def find_available_villas(
    registry: VillaRegistry,
    timelines: dict[str, OccupancyTimeline],
    check_in: date,
    check_out: date,
    persons: int = 1,
    preferred_locations: list[str] | None = None,
    required_attributes: list[str] | None = None,
) -> list[VillaAvailability]:
    """Find all villas available for the entire date range.

    Args:
        registry: Villa metadata registry.
        timelines: Per-villa occupancy timelines.
        check_in: Desired check-in date.
        check_out: Desired check-out date (exclusive).
        persons: Minimum capacity required.
        preferred_locations: Optional list of preferred locations for filtering
            and sorting. Villas in any of these locations rank higher.
        required_attributes: Optional list of required villa attributes.

    Returns:
        List of VillaAvailability results, sorted: available first,
        then available-but-flagged, then unavailable.
    """
    candidates = registry.find_by_capacity(persons)

    # Filter by required attributes
    if required_attributes:
        candidates = [
            v
            for v in candidates
            if all(attr in v.attributes for attr in required_attributes)
        ]

    results = []
    for villa in candidates:
        timeline = timelines.get(villa.name)
        result = check_villa_availability(villa, timeline, check_in, check_out)
        results.append(result)

    # Sort: available first, then flagged, then unavailable
    # Within groups: preferred location match first, then alphabetically
    preferred_set = {loc.lower() for loc in (preferred_locations or [])}

    def sort_key(r: VillaAvailability) -> tuple:
        avail_rank = 0 if r.is_available and not r.is_flagged else 1 if r.is_available else 2
        location_match = 0 if preferred_set and any(
            loc.lower() in preferred_set for loc in r.villa.locations
        ) else 1
        return (avail_rank, location_match, r.villa.name.lower())

    results.sort(key=sort_key)
    return results


def find_available_villas_by_date(
    registry: VillaRegistry,
    timelines: dict[str, OccupancyTimeline],
    check_in: date,
    check_out: date,
    persons: int = 1,
) -> dict[str, set[str]]:
    """Build a date→villas availability map for each day in the range.

    Returns:
        {date: {villa_name, ...}} — for each day, which villas are free.
    """
    from datetime import timedelta

    daily = {}
    current = check_in
    while current < check_out:
        day_end = current + timedelta(days=1)
        candidates = registry.find_by_capacity(persons)
        available = set()
        for villa in candidates:
            timeline = timelines.get(villa.name)
            if timeline is None or timeline.is_available_strict(current, day_end):
                available.add(villa.name)
        daily[current] = available
        current += timedelta(days=1)

    return daily
