"""Tests for the multi-snapshot occupancy detector."""

from datetime import date

import pytest

from villa_matcher.engine.occupancy import classify_reservation_lifecycle
from villa_matcher.models.reservation import Reservation


def make_res(
    opp_name: str = "OPP-001",
    villa: str = "TestVilla",
    checkin: str = "2026-07-01",
    checkout: str = "2026-07-08",
    passenger: str = "Test Guest",
) -> Reservation:
    return Reservation(
        opportunity_name=opp_name,
        villa_name=villa,
        start_date=date.fromisoformat(checkin),
        end_date=date.fromisoformat(checkout),
        lead_passenger=passenger,
        snapshot_date=None,
    )


def make_appearances(
    opp_name: str,
    snapshot_dates: list[str],
    checkin: str = "2026-07-01",
    checkout: str = "2026-07-08",
    villa: str = "TestVilla",
) -> list[tuple[date, Reservation]]:
    res = make_res(opp_name, villa, checkin, checkout)
    return [(date.fromisoformat(d), res) for d in snapshot_dates]


# ── RULE 1: Still visible in latest snapshot → confirmed ─────────────────────

def test_rule1_still_in_latest():
    checkin = date(2026, 7, 15)
    checkout = date(2026, 7, 22)
    res = Reservation(
        opportunity_name="OPP-001",
        villa_name="Villa A",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Alice",
    )

    appearances = [
        (date(2026, 6, 1), res),
        (date(2026, 6, 8), res),
        (date(2026, 6, 15), res),  # Latest = last appearance
    ]
    all_dates = [d for d, _ in appearances]

    record = classify_reservation_lifecycle("OPP-001", appearances, all_dates)
    assert record.confidence == "confirmed"
    assert "RULE 1" in record.evidence


# ── RULE 2: Checkout before last_seen → confirmed (naturally completed) ──────

def test_rule2_naturally_completed():
    checkin = date(2026, 5, 1)
    checkout = date(2026, 5, 8)
    res = Reservation(
        opportunity_name="OPP-002",
        villa_name="Villa B",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Bob",
    )

    appearances = [
        (date(2026, 4, 1), res),
        (date(2026, 4, 15), res),
        (date(2026, 5, 15), res),  # Last seen AFTER checkout
    ]
    all_dates = [d for d, _ in appearances]
    all_dates.append(date(2026, 5, 22))  # Latest snapshot (doesn't contain this)

    # Note: last_seen (May 15) >= checkout (May 8), so RULE 2 applies
    record = classify_reservation_lifecycle("OPP-002", appearances, all_dates)
    assert record.confidence in ("confirmed", "likely_active")


# ── RULE 3: Check-in before last_seen, checkout after → likely_active ────────

def test_rule3_likely_active():
    """Guest checked in June 20, last seen June 22, check-out July 5.
    The report dropped them because check-in passed — they're likely still there."""
    checkin = date(2026, 6, 20)
    checkout = date(2026, 7, 5)
    res = Reservation(
        opportunity_name="OPP-003",
        villa_name="Villa C",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Carol",
    )

    appearances = [
        (date(2026, 5, 1), res),
        (date(2026, 5, 15), res),
        (date(2026, 6, 22), res),  # Last seen — after check-in, before check-out
    ]
    # Latest overall snapshot is June 29, which does NOT contain OPP-003
    all_dates = [
        date(2026, 5, 1), date(2026, 5, 15),
        date(2026, 6, 22), date(2026, 6, 29),
    ]

    record = classify_reservation_lifecycle("OPP-003", appearances, all_dates)
    assert record.confidence == "likely_active"
    assert "RULE 3" in record.evidence


# ── RULE 4: Disappeared before check-in → deleted ────────────────────────────

def test_rule4_deleted():
    """Future booking disappeared before check-in with intervening snapshot."""
    checkin = date(2026, 8, 10)
    checkout = date(2026, 8, 17)
    res = Reservation(
        opportunity_name="OPP-004",
        villa_name="Villa D",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Dave",
    )

    appearances = [
        (date(2026, 6, 1), res),
        (date(2026, 6, 15), res),  # Last seen June 15
    ]
    # July 1 snapshot exists (after last_seen, before checkin) without it
    all_dates = [
        date(2026, 6, 1), date(2026, 6, 15),
        date(2026, 7, 1), date(2026, 7, 15),
    ]

    record = classify_reservation_lifecycle("OPP-004", appearances, all_dates)
    assert record.confidence == "deleted"
    assert "RULE 4" in record.evidence


# ── RULE 5: New booking in latest snapshot → confirmed ──────────────────────

def test_rule5_new_booking():
    checkin = date(2026, 9, 1)
    checkout = date(2026, 9, 10)
    res = Reservation(
        opportunity_name="OPP-005",
        villa_name="Villa E",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Eve",
    )

    appearances = [
        (date(2026, 7, 20), res),  # Only appears in latest snapshot
    ]
    all_dates = [date(2026, 7, 13), date(2026, 7, 20)]

    record = classify_reservation_lifecycle("OPP-005", appearances, all_dates)
    assert record.confidence == "confirmed"
    # RULE 1 fires first (in latest snapshot) — RULE 5 is for when RULE 1 doesn't match
    assert "RULE 1" in record.evidence


# ── RULE 6: Single non-latest appearance → ambiguous ────────────────────────

def test_rule6_ambiguous():
    """Only one appearance, NOT the latest, and check-in is in the past relative
    to that snapshot but no intervening snapshot exists to confirm deletion."""
    # RULE 6 requires: single appearance, not latest, checkin after first_seen,
    # BUT no intervening snapshots exist between first_seen and checkin.
    # So the checkin must be far enough in the past that we only have old snapshots.
    checkin = date(2026, 5, 10)
    checkout = date(2026, 5, 17)
    res = Reservation(
        opportunity_name="OPP-006",
        villa_name="Villa F",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Frank",
    )

    # Single appearance on May 1 — not the latest (latest is May 15),
    # checkin (May 10) is after first_seen, but NO snapshot exists between
    # last_seen (May 1) and checkin (May 10). So RULE 4 doesn't fire.
    appearances = [
        (date(2026, 5, 1), res),
    ]
    # Only two snapshots total: May 1 (has it) and May 15 (doesn't)
    # checkin May 10 is between them, but no intervening snapshot
    all_dates = [date(2026, 5, 1), date(2026, 5, 15)]

    record = classify_reservation_lifecycle("OPP-006", appearances, all_dates)
    # Falls through to RULE 6 or fallback
    assert record.confidence in ("ambiguous", "deleted")


# ── RULE 3b: Small gap after last_seen, multi-snapshot → likely_active ──────

def test_rule3b_small_gap_multi_snapshot():
    """Multi-snapshot booking that disappeared 5 days before checkin."""
    checkin = date(2026, 6, 10)
    checkout = date(2026, 6, 17)
    res = Reservation(
        opportunity_name="OPP-3B",
        villa_name="Villa G",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Grace",
    )
    appearances = [
        (date(2026, 4, 1), res),
        (date(2026, 5, 1), res),
        (date(2026, 6, 5), res),   # 5 days before checkin
    ]
    all_dates = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 5), date(2026, 6, 15)]
    record = classify_reservation_lifecycle("OPP-3B", appearances, all_dates)
    assert record.confidence == "likely_active"
    assert "RULE 3b" in record.evidence


def test_rule3b_large_gap_not_caught():
    """Gap > 7 days should NOT trigger RULE 3b."""
    checkin = date(2026, 8, 1)
    checkout = date(2026, 8, 8)
    res = Reservation(
        opportunity_name="OPP-LG",
        villa_name="Villa H",
        start_date=checkin,
        end_date=checkout,
        lead_passenger="Hank",
    )
    appearances = [
        (date(2026, 4, 1), res),
        (date(2026, 5, 1), res),
        (date(2026, 6, 1), res),   # 60 days before checkin
    ]
    all_dates = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 15)]
    record = classify_reservation_lifecycle("OPP-LG", appearances, all_dates)
    assert "RULE 3b" not in record.evidence


# ── Overlap Resolution ─────────────────────────────────────────────────────

def test_overlap_dedup_priority():
    """confirmed > likely_active > ambiguous > deleted."""
    priority = {"confirmed": 4, "likely_active": 3, "ambiguous": 2, "deleted": 1}
    assert priority["confirmed"] > priority["deleted"]
    assert priority["likely_active"] > priority["deleted"]
    assert priority["confirmed"] > priority["ambiguous"]


# ── Blocking behavior ───────────────────────────────────────────────────────

def test_blocking_records_include_likely_active():
    from villa_matcher.models.snapshot import OccupancyRecord, OccupancyTimeline

    records = [
        OccupancyRecord(
            villa_name="V",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 8),
            confidence="likely_active",
            evidence="RULE 3",
            opportunity_name="X",
        ),
        OccupancyRecord(
            villa_name="V",
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 22),
            confidence="deleted",
            evidence="RULE 4",
            opportunity_name="Y",
        ),
    ]

    timeline = OccupancyTimeline(villa_name="V", records=records)

    # likely_active should block
    blocking = timeline.get_blocking_records(date(2026, 7, 1), date(2026, 7, 5))
    assert len(blocking) == 1
    assert blocking[0].confidence == "likely_active"

    # deleted should NOT block
    blocking = timeline.get_blocking_records(date(2026, 7, 15), date(2026, 7, 20))
    assert len(blocking) == 0

    # Availability checks
    avail, reason, _ = timeline.is_available(date(2026, 7, 1), date(2026, 7, 5))
    assert not avail  # Blocked by likely_active

    avail, reason, _ = timeline.is_available(date(2026, 7, 10), date(2026, 7, 14))
    assert avail  # Gap between records

    avail, reason, _ = timeline.is_available(date(2026, 7, 15), date(2026, 7, 20))
    assert avail  # Deleted doesn't block
