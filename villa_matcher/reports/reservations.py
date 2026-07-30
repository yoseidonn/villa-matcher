"""Reservation extraction — ported from Resital Villa Scripts utils/reservations.py."""

import re

import pandas as pd


def open_xlsx_file_pandas(path: str):
    return pd.read_excel(path)


def extract_reservations(path: str) -> list[dict]:
    """Extract reservations from a Resort Report Excel file."""
    df = open_xlsx_file_pandas(path)
    df.columns = [col.strip() for col in df.columns]

    date_cols = [col for col in df.columns if "Date" in col or "Start" in col or "End" in col]
    for col in date_cols:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d/%m/%y")

    if "ExtrasAggregated" in df.columns:
        df["ExtrasAggregated"] = df["ExtrasAggregated"].fillna("")

    return df.to_dict(orient="records")


def categorise_by_villas(reservations: list[dict]) -> dict[str, list[dict]]:
    """Group reservations by villa name."""
    result = {}
    for r in reservations:
        name = r.get("Accomodation Name") or r.get("Accommodation Name")
        if not name:
            continue
        result.setdefault(name, []).append(r)
    return result


def extract_welcome_pack_size(extras_text: str) -> str:
    match = re.search(r"Welcome Pack\s+([0-9]+-[0-9]+ passengers)", extras_text)
    if match:
        return match.group(1)
    return "Welcome Pack"
