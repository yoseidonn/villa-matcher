#!/usr/bin/env python3
"""Quick standalone script: find available villas for a date range.

Usage:
    python scripts/find_availability.py --from 2026-07-25 --to 2026-08-01 --persons 4
    python scripts/find_availability.py --from 2026-08-01 --to 2026-08-08 --persons 6 --sequences
"""

import os
import sys
from datetime import date
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from villa_matcher.engine.matcher import find_available_villas
from villa_matcher.engine.occupancy import build_occupancy_timelines
from villa_matcher.engine.sequence import find_sequences
from villa_matcher.io.villa_registry import load_villa_registry


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Find available villas")
    parser.add_argument("--from", dest="check_in", required=True, help="Check-in date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="check_out", required=True, help="Check-out date (YYYY-MM-DD)")
    parser.add_argument("--persons", type=int, default=1, help="Number of persons")
    parser.add_argument("--sequences", action="store_true", help="Also find multi-villa sequences")
    parser.add_argument("--min-stay", type=int, default=2, help="Minimum nights per segment")
    parser.add_argument("--max-splits", type=int, default=3, help="Max villas in a sequence")
    parser.add_argument("--location", default="", help="Preferred location")
    parser.add_argument("--villas-json", default="data/villas.json", help="Path to villas.json")
    parser.add_argument("--snapshots-dir", default="", help="Snapshots directory")

    args = parser.parse_args()

    # Parse dates
    ci = date.fromisoformat(getattr(args, "check_in"))
    co = date.fromisoformat(getattr(args, "check_out"))
    total_nights = (co - ci).days

    # Paths
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

    # Load
    registry = load_villa_registry(villas_json)
    timelines, _ = build_occupancy_timelines(snapshots_dir)

    print(f"\n{'='*60}")
    print(f"Search: {ci} → {co} ({total_nights} nights, {args.persons} persons)")
    print(f"{'='*60}")

    # Single villas
    results = find_available_villas(
        registry, timelines, ci, co, persons=args.persons,
        preferred_location=args.location,
    )

    available = [r for r in results if r.is_available and not r.is_flagged]
    flagged = [r for r in results if r.is_available and r.is_flagged]

    if available:
        print(f"\n✓ Available ({len(available)}):")
        for r in available:
            loc = f" [{r.villa.location}]" if r.villa.location else ""
            cap = f" (capacity {r.villa.capacity})" if r.villa.capacity else ""
            print(f"  • {r.villa.name}{loc}{cap}")

    if flagged:
        print(f"\n⚠ Flagged — ambiguous records ({len(flagged)}):")
        for r in flagged:
            loc = f" [{r.villa.location}]" if r.villa.location else ""
            print(f"  • {r.villa.name}{loc}")
            for rec in r.ambiguous_records:
                print(f"      ? {rec.start_date} → {rec.end_date} — {rec.lead_passenger}")

    if not available and not flagged:
        print("\n✗ No villas available for the full period.")

    # Sequences
    if args.sequences:
        print(f"\n--- Multi-Villa Sequences ---")
        sequences = find_sequences(
            registry, timelines, ci, co,
            persons=args.persons, min_stay=args.min_stay,
            max_splits=args.max_splits, preferred_location=args.location,
            max_results=10,
        )

        if sequences:
            for i, seq in enumerate(sequences):
                print(f"\n#{i+1} (score: {seq.score(args.location):.1f})")
                print(f"  {seq.format()}")
        else:
            print("\nNo sequences found.")


if __name__ == "__main__":
    main()
