"""Snapshot loader — loads all report snapshots and builds unified reservation data."""

import os
from collections import defaultdict
from datetime import date

from villa_matcher.io.excel_reader import list_excel_files, read_reservations_excel
from villa_matcher.models.reservation import Reservation


def load_all_snapshots(directory: str) -> list[tuple[date, list[Reservation]]]:
    """Load all Excel snapshots from a directory.

    Returns:
        List of (snapshot_date, reservations) tuples, sorted oldest→newest.
    """
    files = list_excel_files(directory)
    if not files:
        raise FileNotFoundError(f"No Excel files found in: {directory}")

    snapshots = []
    for filepath in files:
        reservations = read_reservations_excel(filepath)
        if reservations:
            snapshot_date = reservations[0].snapshot_date
            if snapshot_date is None:
                # Use file modification time as fallback
                import datetime as dt
                mtime = os.path.getmtime(filepath)
                snapshot_date = dt.datetime.fromtimestamp(mtime).date()
                for r in reservations:
                    r.snapshot_date = snapshot_date
            snapshots.append((snapshot_date, reservations, filepath))

    # Sort by snapshot date
    snapshots.sort(key=lambda s: s[0])

    return [(s[0], s[1]) for s in snapshots]


def build_opportunity_tracker(
    snapshots: list[tuple[date, list[Reservation]]],
) -> dict[str, list[tuple[date, Reservation]]]:
    """
    Build a per-Opportunity-Name tracker showing which snapshots each reservation
    appears in.

    Returns:
        {opportunity_name: [(snapshot_date, reservation), ...]}
        Sorted by snapshot_date.
    """
    tracker: dict[str, list[tuple[date, Reservation]]] = defaultdict(list)

    for snapshot_date, reservations in snapshots:
        for res in reservations:
            if res.opportunity_name:
                tracker[res.opportunity_name].append((snapshot_date, res))

    # Sort each list by snapshot_date
    for key in tracker:
        tracker[key].sort(key=lambda x: x[0])

    return dict(tracker)


def get_all_villa_names(snapshots: list[tuple[date, list[Reservation]]]) -> set[str]:
    """Extract all unique villa names from all snapshots."""
    names = set()
    for _, reservations in snapshots:
        for r in reservations:
            names.add(r.villa_name)
    return names
