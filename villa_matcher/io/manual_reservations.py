"""Manual reservation I/O — load and save data/manual_reservations.json.

Each entry is a manually-confirmed reservation that isn't captured by the
Excel snapshot pipeline. These are merged into occupancy timelines at build
time and treated as authoritative (confidence="confirmed").
"""

import json
import os
import uuid
from datetime import date

from villa_matcher.models.snapshot import OccupancyRecord


def load_manual_reservations(filepath: str) -> list[OccupancyRecord]:
    """Load manual reservations from a JSON file.

    Expected format:
    [
      {
        "villa": "Villa Sudem",
        "start": "2026-07-20",
        "end": "2026-07-27",
        "passenger": "Guest Name",
        "extras": "Pool Heating",
        "notes": "Solmar reservation"
      },
      ...
    ]

    Each entry becomes an OccupancyRecord with confidence="confirmed".
    A unique opportunity_name is generated if not present.
    """
    if not os.path.isfile(filepath):
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = []
    for entry in data:
        try:
            start = date.fromisoformat(entry["start"])
            end = date.fromisoformat(entry["end"])
        except (ValueError, KeyError):
            continue  # Skip malformed entries

        opp_name = entry.get("opportunity_name", "")
        if not opp_name:
            opp_name = f"manual-{uuid.uuid4().hex[:8]}"

        records.append(
            OccupancyRecord(
                villa_name=entry.get("villa", ""),
                start_date=start,
                end_date=end,
                confidence="confirmed",
                evidence="Manual reservation — entered by user."
                         + (f" Notes: {entry['notes']}" if entry.get("notes") else ""),
                opportunity_name=opp_name,
                lead_passenger=entry.get("passenger", ""),
                extras=entry.get("extras", ""),
            )
        )

    return records


def save_manual_reservations(filepath: str, records: list[dict]) -> None:
    """Save manual reservation dicts back to JSON.

    Each dict should have: villa, start, end, passenger, extras, notes
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_manual_reservations_raw(filepath: str) -> list[dict]:
    """Load manual reservations as raw dicts (for API responses)."""
    if not os.path.isfile(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
