"""Excel reader — ported and extended from utils/reservations.py in Resital Villa Scripts.

Reads Resort Report Excel files and extracts Reservation objects,
tagging each with the snapshot date derived from the filename.
"""

import os
import re
from datetime import date, datetime

import pandas as pd

from villa_matcher.models.reservation import Reservation
from villa_matcher.utils.dates import parse_date


def extract_snapshot_date(filepath: str) -> date | None:
    """Extract the snapshot/report date from a filename.

    Typical filename patterns:
      - Resort Report - Resital Group_13-07-2026_unlocked.xlsx
      - Resort Report - Resital Group_20-07-2026.xlsx
      - Report-H6472EGH.xlsx (no date — falls back to file modification time)

    Returns the extracted date or None.
    """
    basename = os.path.basename(filepath)

    # Pattern: DD-MM-YYYY or DD-MM-YY in filename
    match = re.search(r"(\d{2})[-_](\d{2})[-_](\d{4})", basename)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass

    match = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2})", basename)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass

    # Fallback: file modification time
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime).date()
    except OSError:
        pass

    return None


def read_reservations_excel(filepath: str) -> list[Reservation]:
    """Read a single Resort Report Excel file and return Reservation objects.

    Each reservation is tagged with the snapshot date extracted from the filename.
    """
    snapshot_date = extract_snapshot_date(filepath)

    df = pd.read_excel(filepath)
    df.columns = [col.strip() for col in df.columns]

    reservations = []

    for _, row in df.iterrows():
        villa_name = _get_villa_name(row)
        if villa_name is None:
            continue  # Skip "Total" and invalid rows

        start = parse_date(row.get("Holiday Start Date"))
        end = parse_date(row.get("Holiday End Date"))
        if start is None or end is None:
            continue

        opp_name = str(row.get("Opportunity Name", ""))
        if pd.isna(row.get("Opportunity Name")):
            opp_name = ""

        lead = str(row.get("Lead Passenger", ""))
        if pd.isna(row.get("Lead Passenger")):
            lead = ""

        extras = str(row.get("ExtrasAggregated", ""))
        if pd.isna(row.get("ExtrasAggregated")):
            extras = ""

        reservations.append(
            Reservation(
                opportunity_name=opp_name,
                villa_name=villa_name,
                start_date=start,
                end_date=end,
                lead_passenger=lead,
                extras=extras,
                snapshot_date=snapshot_date,
            )
        )

    return reservations


def _get_villa_name(row) -> str | None:
    """Extract villa name, stripping the 'Villa ' prefix and skipping 'Total' rows.

    Normalizes names like 'Villa Tigra' → 'Tigra' so they match the registry.
    """
    for col in ("Accomodation Name", "Accommodation Name"):
        val = row.get(col)
        if val is not None and not pd.isna(val):
            name = str(val).strip()
            if "total" in name.lower():
                return None
            # Strip "Villa " prefix for consistent naming
            if name.lower().startswith("villa "):
                name = name[6:].strip()
            return name
    return None


def list_excel_files(directory: str) -> list[str]:
    """List all .xlsx files in a directory, sorted by name (which reflects date)."""
    if not os.path.isdir(directory):
        return []

    files = []
    for fname in os.listdir(directory):
        if fname.lower().endswith(".xlsx") and not fname.startswith("~"):
            files.append(os.path.join(directory, fname))

    files.sort()
    return files
