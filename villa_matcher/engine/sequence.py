"""Multi-villa sequence finder.

When no single villa is available for the full date range, this finds
sequences of villas (e.g., 3 days in Villa A + 4 days in Villa B) that
collectively cover the entire requested period.

Uses constraint-satisfaction with scoring to rank sequences by:
  1. Fewer moves (villa switches) are better
  2. Same-region transitions are preferred
  3. Preferred location matches get bonus
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import product

from villa_matcher.engine.matcher import find_available_villas_by_date
from villa_matcher.models.snapshot import OccupancyTimeline
from villa_matcher.models.villa import Villa, VillaRegistry


@dataclass
class SequenceSegment:
    """One segment of a multi-villa stay."""

    villa: Villa
    start: date
    end: date  # Exclusive

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


@dataclass
class SequenceMatch:
    """A complete sequence of villa stays covering the requested period."""

    segments: list[SequenceSegment]
    check_in: date
    check_out: date

    @property
    def num_moves(self) -> int:
        return len(self.segments) - 1

    @property
    def total_nights(self) -> int:
        return sum(s.nights for s in self.segments)

    @property
    def same_region_count(self) -> int:
        """Count of adjacent pairs sharing at least one location."""
        count = 0
        for i in range(len(self.segments) - 1):
            prev_locs = {loc.lower() for loc in self.segments[i].villa.locations}
            next_locs = {loc.lower() for loc in self.segments[i + 1].villa.locations}
            if prev_locs & next_locs:
                count += 1
        return count

    @property
    def villa_names(self) -> list[str]:
        return [s.villa.name for s in self.segments]

    def score(self, preferred_locations: list[str] | None = None) -> float:
        """Calculate a ranking score. Higher = better."""
        score = 0.0

        # Base: fewer moves is exponentially better
        score += 40.0 / (1 + self.num_moves)

        # Same-region bonus per adjacent pair
        score += self.same_region_count * 5.0

        # Preferred location bonus
        if preferred_locations:
            preferred_set = {loc.lower() for loc in preferred_locations}
            for seg in self.segments:
                if any(loc.lower() in preferred_set for loc in seg.villa.locations):
                    score += 3.0

        # Fewer unique villas is simpler
        unique_villas = len(set(s.villa.name for s in self.segments))
        score += 3.0 / unique_villas

        return score

    def format(self) -> str:
        """Human-readable sequence description."""
        parts = []
        for i, seg in enumerate(self.segments):
            if i > 0:
                parts.append(" → ")
            parts.append(
                f"{seg.villa.name} ({seg.start.strftime('%d/%m')} — "
                f"{seg.end.strftime('%d/%m')}, {seg.nights} nights)"
            )
        return "".join(parts)


def _generate_partitions(
    total_nights: int, min_stay: int = 2, max_splits: int = 3
) -> list[list[int]]:
    """Generate all valid partitions of total_nights into segments.

    Each segment must be >= min_stay nights.
    Maximum max_splits segments.

    Args:
        total_nights: Total nights to partition.
        min_stay: Minimum nights per segment.
        max_splits: Maximum number of segments (villas).

    Returns:
        List of partitions, each being a list of segment lengths.
    """
    partitions = []

    def backtrack(remaining: int, current: list[int]):
        if len(current) > max_splits:
            return

        if remaining == 0:
            if len(current) >= 1:
                partitions.append(current.copy())
            return

        # The last segment gets whatever's left
        if len(current) == max_splits - 1:
            if remaining >= min_stay:
                current.append(remaining)
                backtrack(0, current)
                current.pop()
            return

        # Try each possible segment length
        for length in range(min_stay, remaining + 1 - min_stay):
            current.append(length)
            backtrack(remaining - length, current)
            current.pop()

        # Also allow the last segment to take all remaining
        if remaining >= min_stay:
            current.append(remaining)
            backtrack(0, current)
            current.pop()

    backtrack(total_nights, [])
    return partitions


def _build_free_intervals(
    villa_name: str,
    timelines: dict[str, OccupancyTimeline],
    query_start: date,
    query_end: date,
) -> list[tuple[date, date]]:
    """Compute contiguous free intervals for a villa within the query range.

    Returns list of (start, end) where the villa is available.
    end is exclusive.
    """
    timeline = timelines.get(villa_name)
    if timeline is None:
        # No data at all — assume fully available
        return [(query_start, query_end)]

    # Collect blocking records within the query range
    blocking = []
    for record in timeline.records:
        if record.is_blocking and record.overlaps(query_start, query_end):
            blocking.append((record.start_date, record.end_date))

    # Sort by start date
    blocking.sort()

    # Merge overlapping blocking periods
    merged = []
    for b_start, b_end in blocking:
        if merged and b_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b_end))
        else:
            merged.append((b_start, b_end))

    # Compute free intervals as gaps between blocking periods
    free = []
    current = query_start

    for b_start, b_end in merged:
        if current < b_start:
            free.append((current, b_start))
        current = max(current, b_end)

    if current < query_end:
        free.append((current, query_end))

    return free


def find_sequences(
    registry: VillaRegistry,
    timelines: dict[str, OccupancyTimeline],
    check_in: date,
    check_out: date,
    persons: int = 1,
    min_stay: int = 2,
    max_splits: int = 3,
    preferred_locations: list[str] | None = None,
    max_results: int = 20,
) -> list[SequenceMatch]:
    """Find multi-villa sequences covering the requested date range.

    Algorithm:
    1. Generate all valid partitions of the date range
    2. For each partition, find available villas per segment
    3. Generate valid sequences (no villa repeated adjacently)
    4. Score and rank

    Args:
        registry: Villa metadata.
        timelines: Occupancy timelines per villa.
        check_in: Desired check-in date.
        check_out: Desired check-out date (exclusive).
        persons: Minimum capacity.
        min_stay: Minimum nights per villa segment.
        max_splits: Maximum number of different villas in a sequence.
        preferred_locations: Locations to boost in scoring and filtering.
        max_results: Maximum sequences to return.

    Returns:
        Ranked list of SequenceMatch objects (best first).
    """
    total_nights = (check_out - check_in).days

    if total_nights < min_stay:
        raise ValueError(
            f"Total stay ({total_nights} nights) shorter than minimum "
            f"segment length ({min_stay} nights)."
        )

    # Filter villas by capacity
    candidates = registry.find_by_capacity(persons)
    if not candidates:
        return []

    # Precompute free intervals for each candidate villa
    villa_intervals: dict[str, list[tuple[date, date]]] = {}
    for villa in candidates:
        intervals = _build_free_intervals(
            villa.name, timelines, check_in, check_out
        )
        if intervals:
            villa_intervals[villa.name] = intervals

    if not villa_intervals:
        return []

    # Generate partitions
    partitions = _generate_partitions(total_nights, min_stay, max_splits)

    # For each partition, find valid villa assignments per segment
    def build_segments(partition: list[int]) -> list[list[SequenceSegment]]:
        """For a given partition, return list of possible assignments per segment."""
        seg_options = []
        day = check_in

        for seg_nights in partition:
            seg_start = day
            seg_end = day + timedelta(days=seg_nights)
            day = seg_end

            # Find villas free for this entire segment
            valid_villas = []
            for villa in candidates:
                intervals = villa_intervals.get(villa.name, [])
                for iv_start, iv_end in intervals:
                    if iv_start <= seg_start and iv_end >= seg_end:
                        valid_villas.append(
                            SequenceSegment(
                                villa=villa,
                                start=seg_start,
                                end=seg_end,
                            )
                        )
                        break  # Only need one interval to cover it

            if not valid_villas:
                return []  # This partition is impossible
            seg_options.append(valid_villas)

        return seg_options

    # Generate all valid sequences
    all_sequences: list[SequenceMatch] = []

    for partition in partitions:
        seg_options = build_segments(partition)
        if not seg_options:
            continue

        # Cartesian product of segment options
        for combo in product(*seg_options):
            # Filter: no adjacent same villa
            valid = True
            for i in range(len(combo) - 1):
                if combo[i].villa.name == combo[i + 1].villa.name:
                    valid = False
                    break

            if not valid:
                continue

            # Filter: no villa appears twice in the sequence
            used_villas = set()
            dup_found = False
            for seg in combo:
                if seg.villa.name in used_villas:
                    dup_found = True
                    break
                used_villas.add(seg.villa.name)
            if dup_found:
                continue

            all_sequences.append(
                SequenceMatch(
                    segments=list(combo),
                    check_in=check_in,
                    check_out=check_out,
                )
            )

    # Score and rank
    all_sequences.sort(
        key=lambda s: s.score(preferred_locations),
        reverse=True,
    )

    return all_sequences[:max_results]


def find_best_options(
    registry: VillaRegistry,
    timelines: dict[str, OccupancyTimeline],
    check_in: date,
    check_out: date,
    persons: int = 1,
    min_stay: int = 2,
    max_splits: int = 3,
    preferred_locations: list[str] | None = None,
) -> dict:
    """Combined search: return single villas + sequences in one call.

    Returns:
        {
            "single_villas": [VillaAvailability, ...],
            "sequences": [SequenceMatch, ...],
            "query": {...},
        }
    """
    from villa_matcher.engine.matcher import find_available_villas

    singles = find_available_villas(
        registry, timelines, check_in, check_out, persons, preferred_locations
    )

    # Only search sequences if fewer than 3 perfectly available singles
    perfect_singles = [s for s in singles if s.is_available and not s.is_flagged]
    if len(perfect_singles) < 3:
        sequences = find_sequences(
            registry,
            timelines,
            check_in,
            check_out,
            persons=persons,
            min_stay=min_stay,
            max_splits=max_splits,
            preferred_locations=preferred_locations,
            max_results=10,
        )
    else:
        sequences = []

    return {
        "single_villas": singles,
        "sequences": sequences,
        "query": {
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "persons": persons,
            "nights": (check_out - check_in).days,
        },
    }
