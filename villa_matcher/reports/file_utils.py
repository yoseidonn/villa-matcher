"""File utilities — ported from utils/file.py."""

import os
import re
from datetime import date, datetime

import openpyxl
from pandas import DataFrame


def select_first_file_with_extension(extension: str, folder: str = "inputs") -> str | None:
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            if fname.lower().endswith(extension.lower()):
                return os.path.join(folder, fname)
    return None


def list_files_with_extension(extension: str, folder: str) -> list[str]:
    files = []
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            if fname.lower().endswith(extension.lower()):
                files.append(os.path.join(folder, fname))
    return files


def select_latest_file_with_extension(extension: str, folder: str) -> str | None:
    """Return the chronologically latest file, by DD-MM-YYYY date embedded in
    the filename (e.g. 'Resort Report ..._03-08-2026_unlocked.xlsx').

    Falls back to `select_first_file_with_extension` if no date can be parsed.
    """
    files = list_files_with_extension(extension, folder)
    if not files:
        return None

    def _key(f: str) -> date:
        m = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", os.path.basename(f))
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        return date.min

    return max(files, key=_key)


def save_report_to_bytes(report, prefix: str = "report") -> tuple[bytes, str, str]:
    """Save a report to an in-memory bytes buffer.

    Returns (bytes_content, filename, mime_type).
    """
    import io

    if isinstance(report, openpyxl.Workbook):
        buf = io.BytesIO()
        report.save(buf)
        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        return buf.read(), f"{prefix}_{ts}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if isinstance(report, DataFrame):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            report.to_excel(writer, index=False)
        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        return buf.read(), f"{prefix}_{ts}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if isinstance(report, str):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        return report.encode("utf-8"), f"{prefix}_{ts}.txt", "text/plain; charset=utf-8"

    raise ValueError(f"Unsupported report type: {type(report)}")


import pandas as pd
