"""File utilities — ported from utils/file.py."""

import os
from datetime import datetime

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
