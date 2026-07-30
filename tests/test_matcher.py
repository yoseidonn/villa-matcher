"""Tests for the villa matcher and sequence finder."""

from datetime import date

import pytest

from villa_matcher.models.villa import Villa, VillaRegistry
from villa_matcher.models.snapshot import OccupancyRecord, OccupancyTimeline
from villa_matcher.engine.matcher import (
    check_villa_availability,
    find_available_villas,
)
from villa_matcher.engine.sequence import (
    SequenceSegment,
    SequenceMatch,
    find_sequences,
    _generate_partitions,
    _build_free_intervals,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_registry(villas_data: list[dict]) -> VillaRegistry:
    villas = []
    for d in villas_data:
        villas.append(Villa(**d))
    return VillaRegistry(villas)


def make_timeline(villa_name: str, records_data: list[dict]) -> OccupancyTimeline:
    records = []
    for d in records_data:
        records.append(
            OccupancyRecord(
                villa_name=villa_name,
                start_date=date.fromisoformat(d["start"]),
                end_date=date.fromisoformat(d["end"]),
                confidence=d["confidence"],
                evidence=d.get("evidence", ""),
                opportunity_name=d.get("opp", ""),
                lead_passenger=d.get("passenger", ""),
            )
        )
    return OccupancyTimeline(villa_name=villa_name, records=records)


# ── Single Villa Matcher Tests ────────────────────────────────────────────────

def test_villa_available_no_bookings():
    villa = Villa(name="FreeVilla", capacity=4, locations=["Kalkan"])
    result = check_villa_availability(
        villa, None, date(2026, 7, 1), date(2026, 7, 8)
    )
    assert result.is_available
    assert not result.is_flagged


def test_villa_blocked_by_confirmed():
    villa = Villa(name="BusyVilla", capacity=6)
    timeline = make_timeline(
        "BusyVilla",
        [
            {
                "start": "2026-07-01",
                "end": "2026-07-10",
                "confidence": "confirmed",
                "passenger": "Alice",
            }
        ],
    )

    # Exact overlap
    result = check_villa_availability(
        villa, timeline, date(2026, 7, 1), date(2026, 7, 8)
    )
    assert not result.is_available

    # Partial overlap
    result = check_villa_availability(
        villa, timeline, date(2026, 7, 5), date(2026, 7, 15)
    )
    assert not result.is_available


def test_villa_available_between_bookings():
    villa = Villa(name="GapVilla", capacity=4)
    timeline = make_timeline(
        "GapVilla",
        [
            {
                "start": "2026-07-01",
                "end": "2026-07-05",
                "confidence": "confirmed",
                "passenger": "Alice",
            },
            {
                "start": "2026-07-10",
                "end": "2026-07-15",
                "confidence": "confirmed",
                "passenger": "Bob",
            },
        ],
    )

    # In the gap
    result = check_villa_availability(
        villa, timeline, date(2026, 7, 5), date(2026, 7, 10)
    )
    assert result.is_available

    # Back-to-back: checkin == existing checkout is allowed
    result = check_villa_availability(
        villa, timeline, date(2026, 7, 5), date(2026, 7, 10)
    )
    assert result.is_available


def test_capacity_filter():
    registry = make_registry(
        [
            {"name": "Small Villa", "capacity": 2, "locations": ["Kalkan"]},
            {"name": "Big Villa", "capacity": 8, "locations": ["Kalkan"]},
            {"name": "Medium Villa", "capacity": 4, "locations": ["Kördere"]},
        ]
    )
    timelines = {}

    results = find_available_villas(
        registry, timelines, date(2026, 7, 1), date(2026, 7, 8), persons=4
    )
    names = {r.villa.name for r in results}
    assert "Small Villa" not in names  # capacity 2 < 4
    assert "Big Villa" in names  # capacity 8 >= 4
    assert "Medium Villa" in names  # capacity 4 >= 4


def test_preferred_location_sorting():
    registry = make_registry(
        [
            {"name": "A Villa", "capacity": 4, "locations": ["İslamlar"]},
            {"name": "B Villa", "capacity": 4, "locations": ["Kalkan"]},
            {"name": "C Villa", "capacity": 4, "locations": ["Kalkan"]},
        ]
    )
    timelines = {}

    results = find_available_villas(
        registry, timelines, date(2026, 7, 1), date(2026, 7, 8),
        persons=4, preferred_locations=["Kalkan"],
    )
    # Kalkan villas should come first
    assert "Kalkan" in results[0].villa.locations
    assert "Kalkan" in results[1].villa.locations
    assert "İslamlar" in results[2].villa.locations


# ── Partition Generation Tests ────────────────────────────────────────────────

def test_partitions_7_nights_min2_max3():
    parts = _generate_partitions(7, min_stay=2, max_splits=3)
    lengths = [tuple(p) for p in parts]

    # Expected: (2,5), (3,4), (4,3), (5,2), (2,2,3), (2,3,2), (3,2,2)
    assert (2, 5) in lengths
    assert (3, 4) in lengths
    assert (2, 2, 3) in lengths
    assert (2, 3, 2) in lengths
    assert (3, 2, 2) in lengths

    # All partitions sum to 7
    for p in parts:
        assert sum(p) == 7

    # Each segment >= min_stay
    for p in parts:
        assert all(seg >= 2 for seg in p)


def test_partitions_min_stay_enforced():
    parts = _generate_partitions(5, min_stay=3, max_splits=2)
    # Only (3,2) and (2,3) — wait, min_stay=3 so (2,3) is invalid
    # Actually (3,2) would have second segment < 3, so it's invalid
    # Only valid: (5,) — single segment
    for p in parts:
        assert all(seg >= 3 for seg in p)


# ── Sequence Finder Tests ────────────────────────────────────────────────────

def test_simple_sequence():
    """Two villas, one unavailable for the full period, sequence needed."""
    registry = make_registry(
        [
            {"name": "Villa A", "capacity": 4, "locations": ["Kalkan"]},
            {"name": "Villa B", "capacity": 4, "locations": ["Kalkan"]},
        ]
    )

    # Villa A: occupied Jul 1-4, free Jul 4-8
    # Villa B: free Jul 1-4, occupied Jul 4-8
    # Sequence: Villa B (Jul 1-4) → Villa A (Jul 4-8)
    timelines = {
        "Villa A": make_timeline(
            "Villa A",
            [{"start": "2026-07-01", "end": "2026-07-04", "confidence": "confirmed"}],
        ),
        "Villa B": make_timeline(
            "Villa B",
            [{"start": "2026-07-04", "end": "2026-07-08", "confidence": "confirmed"}],
        ),
    }

    sequences = find_sequences(
        registry, timelines,
        date(2026, 7, 1), date(2026, 7, 8),
        persons=4, min_stay=2, max_splits=3,
    )

    assert len(sequences) > 0
    # Best sequence should be Villa B → Villa A
    best = sequences[0]
    assert len(best.segments) == 2
    assert best.segments[0].villa.name == "Villa B"
    assert best.segments[1].villa.name == "Villa A"
    assert best.num_moves == 1


def test_no_sequence_when_all_blocked():
    """No villa available at all → no sequences."""
    registry = make_registry(
        [{"name": "Villa A", "capacity": 4, "locations": ["Kalkan"]}]
    )
    timelines = {
        "Villa A": make_timeline(
            "Villa A",
            [{"start": "2026-07-01", "end": "2026-07-08", "confidence": "confirmed"}],
        ),
    }

    sequences = find_sequences(
        registry, timelines,
        date(2026, 7, 1), date(2026, 7, 8),
        persons=4, min_stay=2,
    )

    assert len(sequences) == 0


def test_sequence_no_adjacent_same_villa():
    """Should not generate Villa A → Villa A sequences."""
    registry = make_registry(
        [
            {"name": "Villa A", "capacity": 4, "locations": ["Kalkan"]},
            {"name": "Villa B", "capacity": 4, "locations": ["Kalkan"]},
        ]
    )
    # Both villas completely free
    timelines = {}

    sequences = find_sequences(
        registry, timelines,
        date(2026, 7, 1), date(2026, 7, 7),
        persons=4, min_stay=2, max_splits=3,
    )

    # Every sequence should have unique adjacent villas
    for seq in sequences:
        for i in range(len(seq.segments) - 1):
            assert seq.segments[i].villa.name != seq.segments[i + 1].villa.name


# ── Free Interval Tests ──────────────────────────────────────────────────────

def test_free_intervals_no_bookings():
    intervals = _build_free_intervals(
        "Villa A", {}, date(2026, 7, 1), date(2026, 7, 8)
    )
    assert len(intervals) == 1
    assert intervals[0] == (date(2026, 7, 1), date(2026, 7, 8))


def test_free_intervals_with_booking():
    timelines = {
        "Villa A": make_timeline(
            "Villa A",
            [{"start": "2026-07-03", "end": "2026-07-05", "confidence": "confirmed"}],
        )
    }

    intervals = _build_free_intervals(
        "Villa A", timelines, date(2026, 7, 1), date(2026, 7, 8)
    )
    # Should be: Jul 1-3, Jul 5-8
    assert len(intervals) == 2
    assert intervals[0] == (date(2026, 7, 1), date(2026, 7, 3))
    assert intervals[1] == (date(2026, 7, 5), date(2026, 7, 8))


def test_free_intervals_deleted_doesnt_block():
    timelines = {
        "Villa A": make_timeline(
            "Villa A",
            [{"start": "2026-07-03", "end": "2026-07-05", "confidence": "deleted"}],
        )
    }

    intervals = _build_free_intervals(
        "Villa A", timelines, date(2026, 7, 1), date(2026, 7, 8)
    )
    # Deleted shouldn't block — full range free
    assert len(intervals) == 1
    assert intervals[0] == (date(2026, 7, 1), date(2026, 7, 8))
