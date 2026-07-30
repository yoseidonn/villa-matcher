"""Additional tests for sequence finder edge cases and scoring."""

from datetime import date

import pytest

from villa_matcher.models.villa import Villa, VillaRegistry
from villa_matcher.models.snapshot import OccupancyRecord, OccupancyTimeline
from villa_matcher.engine.sequence import (
    SequenceMatch,
    SequenceSegment,
    find_sequences,
    _generate_partitions,
)


def make_villa(name, capacity=4, locations=None):
    return Villa(name=name, capacity=capacity, locations=locations or [])


# ── Scoring Tests ────────────────────────────────────────────────────────────

def test_score_fewer_moves_better():
    """Sequence with 1 move should score higher than 2 moves."""
    v1 = make_villa("Villa A", locations=["Kalkan"])
    v2 = make_villa("Villa B", locations=["Kalkan"])
    v3 = make_villa("Villa C", locations=["Kalkan"])

    seq_1move = SequenceMatch(
        segments=[
            SequenceSegment(villa=v1, start=date(2026, 7, 1), end=date(2026, 7, 4)),
            SequenceSegment(villa=v2, start=date(2026, 7, 4), end=date(2026, 7, 8)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 8),
    )

    seq_2moves = SequenceMatch(
        segments=[
            SequenceSegment(villa=v1, start=date(2026, 7, 1), end=date(2026, 7, 3)),
            SequenceSegment(villa=v2, start=date(2026, 7, 3), end=date(2026, 7, 6)),
            SequenceSegment(villa=v3, start=date(2026, 7, 6), end=date(2026, 7, 8)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 8),
    )

    assert seq_1move.score() > seq_2moves.score()


def test_score_same_region_bonus():
    """Adjacent villas in same location get bonus."""
    v_kalkan_a = make_villa("Villa A", locations=["Kalkan"])
    v_kalkan_b = make_villa("Villa B", locations=["Kalkan"])
    v_islamlar = make_villa("Villa C", locations=["İslamlar"])

    seq_same_region = SequenceMatch(
        segments=[
            SequenceSegment(villa=v_kalkan_a, start=date(2026, 7, 1), end=date(2026, 7, 4)),
            SequenceSegment(villa=v_kalkan_b, start=date(2026, 7, 4), end=date(2026, 7, 8)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 8),
    )

    seq_diff_region = SequenceMatch(
        segments=[
            SequenceSegment(villa=v_kalkan_a, start=date(2026, 7, 1), end=date(2026, 7, 4)),
            SequenceSegment(villa=v_islamlar, start=date(2026, 7, 4), end=date(2026, 7, 8)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 8),
    )

    assert seq_same_region.score() > seq_diff_region.score()


def test_score_preferred_location():
    """Preferred location gets bonus."""
    v1 = make_villa("Villa A", locations=["Kalkan"])
    v2 = make_villa("Villa B", locations=["İslamlar"])

    seq = SequenceMatch(
        segments=[
            SequenceSegment(villa=v1, start=date(2026, 7, 1), end=date(2026, 7, 8)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 8),
    )

    score_default = seq.score()
    score_kalkan = seq.score(preferred_locations=["Kalkan"])
    assert score_kalkan > score_default


# ── Partition Edge Cases ─────────────────────────────────────────────────────

def test_partition_exact_min_stay():
    """4 nights with min_stay=2 should give (2,2) and (4,)."""
    # Note: min_stay=2, 2-split → (2,2) is valid
    parts = _generate_partitions(4, min_stay=2, max_splits=2)
    lengths = [tuple(p) for p in parts]
    assert (4,) in lengths
    assert (2, 2) in lengths


def test_partition_single_segment_only():
    """When min_stay > total_nights/2, only single segment possible."""
    parts = _generate_partitions(5, min_stay=4, max_splits=3)
    # Only (5,) — (4,1) invalid because 1 < 4, (1,4) same
    assert all(len(p) == 1 for p in parts)


def test_partition_no_solution():
    """When min_stay > total_nights, no valid partitions."""
    parts = _generate_partitions(3, min_stay=5, max_splits=3)
    assert len(parts) == 0


# ── Sequence Formatting ──────────────────────────────────────────────────────

def test_sequence_format():
    v1 = make_villa("Villa A", locations=["Kalkan"])
    v2 = make_villa("Villa B", locations=["Kalkan"])
    seq = SequenceMatch(
        segments=[
            SequenceSegment(villa=v1, start=date(2026, 7, 1), end=date(2026, 7, 4)),
            SequenceSegment(villa=v2, start=date(2026, 7, 4), end=date(2026, 7, 7)),
        ],
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 7),
    )

    formatted = seq.format()
    assert "Villa A" in formatted
    assert "Villa B" in formatted
    assert "→" in formatted
    assert seq.total_nights == 6
    assert seq.num_moves == 1
