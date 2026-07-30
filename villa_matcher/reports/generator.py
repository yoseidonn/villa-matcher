"""Report generator — ported from Resital Villa Scripts utils/reports.py.

Generates all report types:
  - weekly (caretaker-based villa assignments)
  - ismet_abi (reservations with welcome pack + pool heating)
  - hamdi_abi (unassigned villas)
  - korsan (calendar-style Excel workbook)
  - total_history (merged all-time reservations)
"""

import json
import os
import re
import warnings
from datetime import datetime, timedelta

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from villa_matcher.reports.caretakers import get_caretakers
from villa_matcher.reports.file_utils import list_files_with_extension
from villa_matcher.reports.reservations import (
    categorise_by_villas,
    extract_reservations,
    extract_welcome_pack_size,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _filter_extras_text(extras: str) -> str:
    if not isinstance(extras, str):
        return ""
    matches = re.findall(r"(1x Extra - (Welcome Pack\s+\d+-\d+ passengers|Pool Heating)[^,]*)", extras)
    filtered = [m[0] for m in matches]
    return ", ".join(filtered)


def _format_date_columns(df, date_columns: dict):
    """Format date columns in a DataFrame."""
    for col, fmt in date_columns.items():
        if col not in df.columns:
            continue
        if df[col].dtype == "object" and df[col].str.contains(r"\d{2}/\d{2}/\d{2}", na=False).all():
            continue
        try:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime(fmt)
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime(fmt)
        except Exception:
            pass


DATE_COLS = {
    "Holiday Start Date": "%d/%m/%y",
    "Holiday End Date": "%d/%m/%y",
    "Departure Date": "%d/%m/%y",
    "Departure Flight Time": "%H:%M",
    "Flight Arrival Time": "%H:%M",
    "Flight Arrival Date": "%d/%m/%y",
}


# ── Weekly Report ───────────────────────────────────────────────────────────

def weekly_report(excel_path: str, caretakers_path: str) -> str:
    """Generate caretaker-based weekly villa report."""
    caretakers = get_caretakers(caretakers_path)
    if caretakers and isinstance(caretakers[0], str):
        raise ValueError(f"Wrong file — expected caretakers.json, got a string list.")

    reservations = extract_reservations(excel_path)
    reservations = sorted(
        reservations,
        key=lambda r: (
            pd.to_datetime(r.get("Holiday Start Date") or "", format="%d/%m/%y", errors="coerce"),
            str(r.get("Accomodation Name", "")),
        ),
    )
    reservations_by_villas = categorise_by_villas(reservations)

    for ct in caretakers:
        output = f"---- {ct['name']} ----\n"
        for assignment_name, extras_cfg in ct["assignments"].items():
            output += f"\n*{assignment_name}*\n"
            villa_name = f"Villa {assignment_name}"
            villa_res = reservations_by_villas.get(villa_name, [])
            if not villa_res:
                output += "\nReservasyon yok"
            else:
                for r in villa_res:
                    start = r.get("Holiday Start Date") or r.get("Holiday Start Day")
                    end = r.get("Holiday End Date")
                    output += f"{start} - {end}"
                    extra = ""
                    extras_text = r.get("ExtrasAggregated", "")
                    if extras_cfg.get("poolHeating") and "Pool Heating" in extras_text:
                        extra += " (Havuz ısıtması"
                    if extras_cfg.get("complimentaryCot") and "Complimentary Cot" in extras_text:
                        extra += ", bebek yatağı" if extra else " (Bebek yatağı"
                    if extras_cfg.get("welcomePack") and "Welcome Pack" in extras_text:
                        wp = extract_welcome_pack_size(extras_text)
                        extra += f", {wp})\n" if extra else f" ({wp})\n"
                    else:
                        extra += ")\n" if extra else "\n"
                    output += extra
        ct["output"] = output

    return "\n\n".join([ct["output"] for ct in caretakers])


# ── İsmet Abi Report ────────────────────────────────────────────────────────

def ismet_abi_report(folder: str = "inputs/all_reservations") -> pd.DataFrame:
    """Reservations with Welcome Pack and/or Pool Heating extras."""
    files = list_files_with_extension(".xlsx", folder)
    all_res = []
    for file in files:
        all_res.append(pd.read_excel(file))
    if not all_res:
        return pd.DataFrame()
    merged = pd.concat(all_res, ignore_index=True)

    if "Opportunity Name" in merged.columns:
        def _has_relevant_extras(extras):
            if pd.isna(extras):
                return False
            return "Welcome Pack" in str(extras) or "Pool Heating" in str(extras)

        merged["__has"] = merged["ExtrasAggregated"].apply(_has_relevant_extras)
        merged = merged.sort_values(by=["Opportunity Name", "__has"], ascending=[True, False])
        merged = merged.drop_duplicates(subset=["Opportunity Name"], keep="first")
        merged = merged.drop(columns=["__has"])

    if "ExtrasAggregated" in merged.columns:
        merged["ExtrasAggregated"] = merged["ExtrasAggregated"].apply(_filter_extras_text)
        merged = merged[merged["ExtrasAggregated"].str.strip() != ""]

    if "Holiday Start Date" in merged.columns:
        merged["__sort"] = pd.to_datetime(merged["Holiday Start Date"], errors="coerce")
        sort_cols = ["__sort", "Accomodation Name"] if "Accomodation Name" in merged.columns else ["__sort"]
        merged = merged.sort_values(by=sort_cols, ascending=True)
        merged = merged.drop(columns=["__sort"])

    _format_date_columns(merged, DATE_COLS)
    return merged


# ── Hamdi Abi Report ────────────────────────────────────────────────────────

def hamdi_abi_report(inputs_folder: str = "inputs", caretakers_path: str = "inputs/caretakers.json") -> str:
    """Report for villas NOT assigned to any caretaker."""
    files = list_files_with_extension(".xlsx", inputs_folder)
    if not files:
        return "Excel dosyası bulunamadı"

    df = pd.read_excel(files[0])
    assigned = set()
    caretakers = get_caretakers(caretakers_path)
    for ct in caretakers:
        assigned.update(f"Villa {v}" for v in ct["assignments"].keys())

    hamdi = df[~df["Accomodation Name"].isin(assigned)].copy()
    hamdi = hamdi[~hamdi["Accomodation Name"].str.contains("Total", na=False)]

    if "ExtrasAggregated" in hamdi.columns:
        hamdi["ExtrasAggregated"] = hamdi["ExtrasAggregated"].apply(_filter_extras_text)

    if "Holiday Start Date" in hamdi.columns:
        hamdi["__sort"] = pd.to_datetime(hamdi["Holiday Start Date"], errors="coerce")
        sort_cols = ["__sort", "Accomodation Name"] if "Accomodation Name" in hamdi.columns else ["__sort"]
        hamdi = hamdi.sort_values(by=sort_cols, ascending=True)
        hamdi = hamdi.drop(columns=["__sort"])

    _format_date_columns(hamdi, DATE_COLS)

    output = "---- Hamdi Abi ----\n"
    output += f"Kullanılan dosya: {os.path.basename(files[0])}\n\n"

    if len(hamdi) == 0:
        output += "Rezervasyon yok"
    else:
        for villa_name, group in hamdi.groupby("Accomodation Name"):
            clean = villa_name.replace("Villa ", "")
            output += f"\n*{clean}*\n"
            for _, r in group.iterrows():
                start = r.get("Holiday Start Date", "")
                end = r.get("Holiday End Date", "")
                extras = r.get("ExtrasAggregated", "")
                if pd.notna(extras) and extras.strip():
                    output += f"{start} - {end} ({extras})\n"
                else:
                    output += f"{start} - {end}\n"

    # Stats
    all_villas = {v for v in df["Accomodation Name"].unique() if "Total" not in str(v)}
    hamdi_set = set(hamdi["Accomodation Name"].unique())
    output += f"\n\n--- İstatistik ---\n"
    output += f"Toplam: {len(all_villas)} | Atanmış: {len(assigned)} | Hamdi: {len(hamdi_set)}\n"
    return output


# ── Total History Report ────────────────────────────────────────────────────

def total_history_report(folder: str = "inputs/all_reservations") -> pd.DataFrame:
    """All reservations merged from every snapshot, deduplicated."""
    files = list_files_with_extension(".xlsx", folder)
    all_res = []
    for file in files:
        all_res.append(pd.read_excel(file))
    if not all_res:
        return pd.DataFrame()
    merged = pd.concat(all_res, ignore_index=True)

    if "Opportunity Name" in merged.columns:
        merged = merged.drop_duplicates(subset=["Opportunity Name"], keep="last")

    if "Holiday Start Date" in merged.columns:
        merged["__sort"] = pd.to_datetime(merged["Holiday Start Date"], errors="coerce")
        sort_cols = ["__sort", "Accomodation Name"] if "Accomodation Name" in merged.columns else ["__sort"]
        merged = merged.sort_values(by=sort_cols, ascending=True)
        merged = merged.drop(columns=["__sort"])

    _format_date_columns(merged, DATE_COLS)
    return merged


# ── Korsan Villas Report ────────────────────────────────────────────────────

def korsan_villas_report(
    excel_path: str,
    korsan_villas_json: str,
    template_path: str,
    year: int = 2026,
) -> openpyxl.Workbook:
    """Calendar-style Excel workbook — one sheet per month, May-Nov."""
    months = {
        5: ("Mayıs", 31), 6: ("Haziran", 30), 7: ("Temmuz", 31),
        8: ("Ağustos", 31), 9: ("Eylül", 30), 10: ("Ekim", 31), 11: ("Kasım", 30),
    }

    with open(korsan_villas_json, "r", encoding="utf-8") as f:
        villa_names = json.load(f)
    all_villas = {f"Villa {n}" for n in villa_names}

    df = pd.read_excel(excel_path)
    df.columns = [col.strip() for col in df.columns]
    df = df[df["Accomodation Name"].isin(all_villas)].copy()
    df = df[~df["Accomodation Name"].str.contains("Total", na=False)]

    if not pd.api.types.is_datetime64_any_dtype(df["Holiday Start Date"]):
        df["Holiday Start Date"] = pd.to_datetime(df["Holiday Start Date"], errors="coerce")
    if not pd.api.types.is_datetime64_any_dtype(df["Holiday End Date"]):
        df["Holiday End Date"] = pd.to_datetime(df["Holiday End Date"], errors="coerce")

    if "ExtrasAggregated" in df.columns:
        df["ExtrasAggregated"] = df["ExtrasAggregated"].apply(_filter_extras_text)

    wb = openpyxl.load_workbook(template_path)
    sorted_villas = sorted(all_villas, key=lambda v: v.replace("Villa ", "").lower())

    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    villa_font = Font(name="Arial", size=11, bold=True)
    cell_font = Font(name="Arial", size=9)
    cell_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    villa_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style="thin", color="999999"),
        right=Side(style="thin", color="999999"),
        top=Side(style="thin", color="999999"),
        bottom=Side(style="thin", color="999999"),
    )

    for month_num, (sheet_name, days_in_month) in months.items():
        ws = wb[sheet_name]
        month_start = datetime(year, month_num, 1)
        month_end = datetime(year, month_num, days_in_month, 23, 59, 59)
        ws.row_dimensions[1].height = 30

        villa_row_map = {}
        for i, vf in enumerate(sorted_villas):
            row = i + 2
            ws.row_dimensions[row].height = 30
            cell = ws.cell(row=row, column=1, value=vf.replace("Villa ", ""))
            cell.font = villa_font
            cell.alignment = villa_align
            villa_row_map[vf] = row

        max_name = max(len(v.replace("Villa ", "")) for v in sorted_villas)
        ws.column_dimensions["A"].width = max_name + 3
        for col_idx in range(2, days_in_month + 2):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 4

        for _, res in df.iterrows():
            start, end = res["Holiday Start Date"], res["Holiday End Date"]
            if pd.isna(start) or pd.isna(end):
                continue
            villa = res["Accomodation Name"]
            if villa not in villa_row_map:
                continue
            res_start = max(start, month_start)
            res_end = min(end - timedelta(days=1), month_end)
            if res_start > res_end:
                continue

            passenger = str(res.get("Lead Passenger", "")) if not pd.isna(res.get("Lead Passenger")) else ""
            extras = str(res.get("ExtrasAggregated", "")) if not pd.isna(res.get("ExtrasAggregated")) else ""
            cell_text = f"{passenger}\n({extras})" if extras else passenger

            row = villa_row_map[villa]
            start_col, end_col = res_start.day + 1, res_end.day + 1

            def _apply(c, fill, font, align):
                c.fill, c.font, c.alignment = fill, font, align

            if start_col == end_col:
                c = ws.cell(row=row, column=start_col)
                c.value = cell_text
                _apply(c, green_fill, cell_font, cell_align)
                c.border = thin_border
            else:
                ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
                c = ws.cell(row=row, column=start_col)
                c.value = cell_text
                _apply(c, green_fill, cell_font, cell_align)
                for col in range(start_col, end_col + 1):
                    ws.cell(row=row, column=col).fill = green_fill
                    ws.cell(row=row, column=col).border = thin_border

    return wb
