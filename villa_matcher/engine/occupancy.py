"""Multi-snapshot occupancy detector.

Core algorithm: by analyzing ALL report snapshots sorted by date, classify
every reservation's lifecycle to distinguish:
  - Confirmed bookings (visible in latest snapshot, or naturally completed)
  - Likely-active stays (check-in passed, guest still there — the report
    dropped the row because check-in date passed, NOT a deletion)
  - Deleted reservations (future booking disappeared before check-in)
  - Ambiguous cases (insufficient data to determine)

The six classification rules are the key insight from the existing
compare_reports.py approach, generalized across N snapshots.
"""

from collections import defaultdict
from datetime import date, timedelta

from villa_matcher.io.snapshot_loader import (
    build_opportunity_tracker,
    load_all_snapshots,
)
from villa_matcher.models.reservation import Reservation
from villa_matcher.models.snapshot import OccupancyRecord, OccupancyTimeline


def classify_reservation_lifecycle(
    opportunity_name: str,
    appearances: list[tuple[date, Reservation]],
    all_snapshot_dates: list[date],
) -> OccupancyRecord:
    """
    Classify a single reservation's lifecycle using the 6-rule system.

    Args:
        opportunity_name: The unique reservation ID.
        appearances: List of (snapshot_date, reservation) this ID appears in,
                     sorted by snapshot_date.
        all_snapshot_dates: All snapshot dates in the dataset, sorted.

    Returns:
        OccupancyRecord with confidence classification and evidence.
    """
    if not appearances:
        raise ValueError(f"No appearances for {opportunity_name}")

    # Use the reservation data from the latest appearance (most up-to-date)
    latest_res = appearances[-1][1]

    first_seen = appearances[0][0]
    last_seen = appearances[-1][0]
    checkin = latest_res.start_date
    checkout = latest_res.end_date
    latest_snapshot = all_snapshot_dates[-1]

    evidence_parts = [
        f"First seen: {first_seen}, Last seen: {last_seen}",
        f"Check-in: {checkin}, Check-out: {checkout}",
    ]

    # ── RULE 1: Still visible in the latest snapshot ─────────────────
    if last_seen == latest_snapshot:
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="confirmed",
            evidence="RULE 1: Still visible in latest snapshot — active/future booking."
            + " | ".join(evidence_parts),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    # ── RULE 2: Check-out before the snapshot that dropped it ────────
    # The reservation naturally completed before the snapshot was taken.
    if checkout <= last_seen:
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="confirmed",
            evidence=(
                "RULE 2: Check-out <= last seen snapshot date — "
                "reservation naturally completed before next snapshot. "
                + " | ".join(evidence_parts)
            ),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    # ── RULE 3: Check-out > last_seen AND check-in <= last_seen ──────
    # Guest checked in before the last snapshot that showed them,
    # and their check-out is after. The report dropped them because
    # check-in passed — NOT a deletion. Guest is likely still there.
    if checkout > last_seen and checkin <= last_seen:
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="likely_active",
            evidence=(
                "RULE 3: Check-out after last seen AND check-in before "
                "or on last seen — guest likely still in villa; report "
                "dropped row because check-in date passed. "
                + " | ".join(evidence_parts)
            ),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    # ── RULE 3b: Small gap after last_seen, multi-snapshot booking ────
    # Reservation appeared in ≥2 snapshots (real tracked booking),
    # disappeared within 7 days of check-in (weekly snapshot cycle gap).
    # These are almost certainly real stays — the snapshot cadence
    # just didn't catch the exact check-in moment. Same logic as RULE 3
    # but with a small tolerance window.
    gap_days = (checkin - last_seen).days
    if len(appearances) >= 2 and checkout > last_seen and 1 <= gap_days <= 7:
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="likely_active",
            evidence=(
                f"RULE 3b: Multi-snapshot booking ({len(appearances)} appearances) "
                f"disappeared only {gap_days} days before check-in — "
                f"consistent with weekly snapshot cycle; guest likely there. "
                + " | ".join(evidence_parts)
            ),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    # ── RULE 4: Check-in after last_seen → potential deletion ───────
    # The reservation disappeared before check-in. Check if there's a
    # snapshot after last_seen but before check-in that should have it.
    if checkin > last_seen:
        intervening_snapshots = [
            d for d in all_snapshot_dates if last_seen < d <= checkin
        ]
        if intervening_snapshots:
            # At least one snapshot was taken between last appearance
            # and check-in — the reservation was genuinely deleted.
            return OccupancyRecord(
                villa_name=latest_res.villa_name,
                start_date=checkin,
                end_date=checkout,
                confidence="deleted",
                evidence=(
                    "RULE 4: Check-in after last seen AND intervening "
                    f"snapshot(s) exist ({intervening_snapshots}) — "
                    "reservation was deleted before check-in. "
                    + " | ".join(evidence_parts)
                ),
                opportunity_name=opportunity_name,
                lead_passenger=latest_res.lead_passenger,
                extras=latest_res.extras,
            )

    # ── RULE 5: Only one appearance AND it's the latest snapshot ─────
    if len(appearances) == 1 and first_seen == latest_snapshot:
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="confirmed",
            evidence=(
                "RULE 5: Only appears in latest snapshot — new booking. "
                + " | ".join(evidence_parts)
            ),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    # ── RULE 6: Only one appearance, NOT the latest, check-in after ──
    if len(appearances) == 1 and first_seen != latest_snapshot:
        if checkin > first_seen:
            return OccupancyRecord(
                villa_name=latest_res.villa_name,
                start_date=checkin,
                end_date=checkout,
                confidence="ambiguous",
                evidence=(
                    "RULE 6: Only appears in one non-latest snapshot, "
                    "check-in after that snapshot — might be deleted or "
                    "might have been a temporary hold. Manual review needed. "
                    + " | ".join(evidence_parts)
                ),
                opportunity_name=opportunity_name,
                lead_passenger=latest_res.lead_passenger,
                extras=latest_res.extras,
            )

    # ── Fallback: doesn't match any explicit rule ──────────────────
    # Multi-snapshot bookings (>1 appearance) with past checkin but
    # gap > 7 days: still more likely real than not. Classify as
    # likely_active with a wider-tolerance note.
    # Single-snapshot bookings with past checkin: truly ambiguous.
    if len(appearances) >= 2 and checkin <= latest_snapshot:
        gap = (checkin - last_seen).days
        return OccupancyRecord(
            villa_name=latest_res.villa_name,
            start_date=checkin,
            end_date=checkout,
            confidence="likely_active",
            evidence=(
                f"FALLBACK-A: Multi-snapshot booking ({len(appearances)} appearances) "
                f"with past check-in (gap={gap}d). Likely a real stay "
                f"that completed before snapshot coverage caught the checkout. "
                + " | ".join(evidence_parts)
            ),
            opportunity_name=opportunity_name,
            lead_passenger=latest_res.lead_passenger,
            extras=latest_res.extras,
        )

    return OccupancyRecord(
        villa_name=latest_res.villa_name,
        start_date=checkin,
        end_date=checkout,
        confidence="ambiguous",
        evidence=(
            f"FALLBACK-B: Single snapshot or unclear timeline. "
            + " | ".join(evidence_parts)
        ),
        opportunity_name=opportunity_name,
        lead_passenger=latest_res.lead_passenger,
        extras=latest_res.extras,
    )


def build_occupancy_timelines(
    snapshots_dir: str,
    manual_records: list[OccupancyRecord] | None = None,
) -> tuple[dict[str, OccupancyTimeline], list[date]]:
    """
    Build OccupancyTimeline objects for all villas from all snapshots,
    optionally merged with manual reservation records.

    Args:
        snapshots_dir: Directory containing Resort Report .xlsx files.
        manual_records: Optional list of manually-entered OccupancyRecords
            that are merged into the timelines as authoritative (confirmed).

    Returns:
        (villa_timelines, all_snapshot_dates)
        villa_timelines: {villa_name: OccupancyTimeline}
        all_snapshot_dates: sorted list of all snapshot dates
    """
    # 1. Load all snapshots
    snapshots = load_all_snapshots(snapshots_dir)
    if not snapshots:
        raise FileNotFoundError(f"No snapshots found in {snapshots_dir}")

    all_snapshot_dates = [s[0] for s in snapshots]

    # 2. Build opportunity tracker
    tracker = build_opportunity_tracker(snapshots)

    # 3. Classify each opportunity
    records_by_villa: dict[str, list[OccupancyRecord]] = defaultdict(list)

    for opp_name, appearances in tracker.items():
        record = classify_reservation_lifecycle(
            opp_name, appearances, all_snapshot_dates
        )
        records_by_villa[record.villa_name].append(record)

    # 3b. Resolve overlapping records: when two records cover the exact
    #     same date range for the same villa (duplicate/rebooked reservation),
    #     drop the "deleted" one in favor of the blocking one.
    for villa_name in records_by_villa:
        records = records_by_villa[villa_name]
        # Group by (start_date, end_date)
        from collections import defaultdict as dd
        by_dates: dict[tuple, list[OccupancyRecord]] = dd(list)
        for r in records:
            by_dates[(r.start_date, r.end_date)].append(r)

        resolved = []
        for (s, e), group in by_dates.items():
            if len(group) == 1:
                resolved.append(group[0])
            else:
                # Prefer: confirmed > likely_active > ambiguous > deleted
                priority = {"confirmed": 4, "likely_active": 3, "ambiguous": 2, "deleted": 1}
                best = max(group, key=lambda r: priority.get(r.confidence, 0))
                resolved.append(best)
                dropped = [r for r in group if r is not best]
                for d in dropped:
                    best.evidence += (
                        f" | Overlap resolved: dropped {d.confidence} record "
                        f"(Opp: {d.opportunity_name}) covering same dates."
                    )

        records_by_villa[villa_name] = resolved

    # 3c. Merge manual reservations — manual records are authoritative.
    #     If a manual record overlaps with a snapshot record for the same
    #     villa and exact date range, the manual record replaces it.
    #     Non-overlapping manual records are appended.
    if manual_records:
        for mr in manual_records:
            vname = mr.villa_name
            if vname not in records_by_villa:
                records_by_villa[vname] = []
            existing = records_by_villa[vname]
            # Remove snapshot records that exactly match this date range
            existing = [
                r for r in existing
                if not (r.start_date == mr.start_date and r.end_date == mr.end_date)
            ]
            existing.append(mr)
            records_by_villa[vname] = existing

    # 4. Build OccupancyTimeline per villa
    timelines: dict[str, OccupancyTimeline] = {}
    for villa_name, records in records_by_villa.items():
        timeline = OccupancyTimeline(
            villa_name=villa_name,
            records=sorted(records, key=lambda r: r.start_date),
        )
        timelines[villa_name] = timeline

    return timelines, all_snapshot_dates


def get_occupancy_summary(
    timelines: dict[str, OccupancyTimeline],
) -> dict:
    """Generate summary statistics about occupancy classifications."""
    summary = {
        "total_villas": len(timelines),
        "total_records": 0,
        "confirmed": 0,
        "likely_active": 0,
        "ambiguous": 0,
        "deleted": 0,
        "villa_details": {},
    }

    for villa_name, timeline in timelines.items():
        villa_stats = {
            "confirmed": 0,
            "likely_active": 0,
            "ambiguous": 0,
            "deleted": 0,
            "total": len(timeline.records),
        }
        for record in timeline.records:
            summary["total_records"] += 1
            key = record.confidence
            if key in villa_stats:
                villa_stats[key] += 1
            if key in summary:
                summary[key] += 1

        summary["villa_details"][villa_name] = villa_stats

    return summary


def filter_timelines_to_period(
    timelines: dict[str, OccupancyTimeline],
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, OccupancyTimeline]:
    """Filter timelines to only include records that overlap a date range.

    If period_start/end are None, no filtering is applied on that side.
    """
    if period_start is None and period_end is None:
        return timelines

    filtered = {}
    for villa_name, timeline in timelines.items():
        relevant = []
        for record in timeline.records:
            # Keep if record overlaps the period
            rec_end = record.end_date
            rec_start = record.start_date

            if period_end and rec_start >= period_end:
                continue
            if period_start and rec_end <= period_start:
                continue
            relevant.append(record)

        if relevant:
            filtered[villa_name] = OccupancyTimeline(
                villa_name=villa_name, records=relevant
            )

    return filtered
