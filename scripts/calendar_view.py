#!/usr/bin/env python3
"""Quick standalone script: view a villa's occupancy calendar.

Usage:
    python scripts/calendar_view.py --villa "Samira One" --month 7 --year 2026
    python scripts/calendar_view.py --interactive
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="View villa occupancy calendar")
    parser.add_argument("--villa", default=None, help="Villa name")
    parser.add_argument("--month", type=int, default=None, help="Month (1-12)")
    parser.add_argument("--year", type=int, default=None, help="Year")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--villas-json", default="data/villas.json")
    parser.add_argument("--snapshots-dir", default="")

    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent
    villas_json = args.villas_json
    if not os.path.isabs(villas_json):
        villas_json = str(base / villas_json)

    snapshots_dir = args.snapshots_dir
    if not snapshots_dir:
        legacy = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/all_reservations"
        if os.path.isdir(legacy):
            snapshots_dir = legacy
        else:
            snapshots_dir = str(base / "data" / "all_reservations")

    from villa_matcher.io.villa_registry import load_villa_registry
    from villa_matcher.engine.occupancy import build_occupancy_timelines

    registry = load_villa_registry(villas_json)

    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir)
    except FileNotFoundError:
        print(f"No snapshots found at {snapshots_dir}")
        timelines = {}

    today = date.today()
    year = args.year or today.year
    month = args.month or today.month

    if args.interactive:
        from villa_matcher.calendar.terminal import run_interactive_calendar
        run_interactive_calendar(
            registry, timelines,
            start_villa=args.villa,
            start_year=year, start_month=month,
        )
    else:
        from villa_matcher.calendar.terminal import print_calendar_static
        villa = args.villa or registry.names[0]
        if villa not in registry:
            print(f"Villa '{villa}' not found.")
            print(f"Available: {', '.join(registry.names[:10])}...")
            return

        v = registry.get(villa)
        timeline = timelines.get(villa)
        print_calendar_static(villa, year, month, timeline, v)


if __name__ == "__main__":
    main()
