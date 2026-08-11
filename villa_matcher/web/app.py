"""FastAPI web application for Villa Matcher.

Provides REST API endpoints wrapping the villa-matcher engine,
and serves the single-page frontend.
"""

import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from villa_matcher.engine.occupancy import (
    build_occupancy_timelines,
    get_occupancy_summary,
)
from villa_matcher.engine.matcher import find_available_villas
from villa_matcher.engine.sequence import find_sequences
from villa_matcher.io.villa_registry import load_villa_registry
from villa_matcher.io.manual_reservations import (
    load_manual_reservations,
    load_manual_reservations_raw,
    save_manual_reservations,
)
from villa_matcher.calendar.render import build_month_grid, CalendarMonth


# ── Paths ────────────────────────────────────────────────────────────────────

def _get_data_dir() -> str:
    pkg_dir = Path(__file__).resolve().parent.parent.parent
    return str(pkg_dir / "data")


def _get_snapshots_dir() -> str:
    data_dir = Path(_get_data_dir())
    snapshots = data_dir / "all_reservations"
    if snapshots.is_dir():
        import os as _os
        xlsx = [f for f in _os.listdir(str(snapshots)) if f.endswith(".xlsx")]
        if xlsx:
            return str(snapshots)
    legacy = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/all_reservations"
    if os.path.isdir(legacy):
        return legacy
    return str(snapshots)


# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Villa Matcher",
    description="Villa availability engine with multi-snapshot occupancy detection",
    version="0.1.0",
)

# Load data at startup
_villas_json = os.path.join(_get_data_dir(), "villas.json")
_manual_reservations_json = os.path.join(_get_data_dir(), "manual_reservations.json")
_snapshots_dir = _get_snapshots_dir()

_registry = None
_timelines = {}
_snapshot_dates = []
_manual_records = []


def _ensure_loaded():
    global _registry, _timelines, _snapshot_dates, _manual_records
    if _registry is None:
        try:
            _registry = load_villa_registry(_villas_json)
        except FileNotFoundError:
            _registry = None
        try:
            _manual_records = load_manual_reservations(_manual_reservations_json)
        except Exception:
            _manual_records = []
        try:
            _timelines, _snapshot_dates = build_occupancy_timelines(
                _snapshots_dir, manual_records=_manual_records
            )
        except FileNotFoundError:
            _timelines = {}


# ── API Endpoints ─────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/villas")
def list_villas():
    """Get all villa names and metadata."""
    _ensure_loaded()
    if _registry is None:
        return JSONResponse({"error": "No villa registry loaded"}, status_code=500)

    villas = []
    for v in _registry.all_villas:
        timeline = _timelines.get(v.name)
        occupancies = []
        if timeline:
            for r in timeline.records:
                occupancies.append({
                    "start": r.start_date.isoformat(),
                    "end": r.end_date.isoformat(),
                    "confidence": r.confidence,
                    "passenger": r.lead_passenger,
                    "extras": r.extras,
                    "evidence": r.evidence[:150] if r.evidence else "",
                    "opportunity": r.opportunity_name,
                })

        villas.append({
            "name": v.name,
            "capacity": v.capacity,
            "locations": v.locations,
            "area": v.area,
            "bedrooms": v.bedrooms,
            "bathrooms": v.bathrooms,
            "attributes": v.attributes,
            "resital_url": v.resital_url,
            "solmar_url": v.solmar_url,
            "occupancy_count": len(occupancies),
            "occupancies": occupancies,
        })

    return {"villas": villas, "total": len(villas)}


@app.get("/api/villas/{villa_name}")
def get_villa(villa_name: str):
    """Get a single villa with its occupancy timeline."""
    _ensure_loaded()
    if _registry is None:
        return JSONResponse({"error": "No villa registry loaded"}, status_code=500)

    v = _registry.get(villa_name)
    if v is None:
        return JSONResponse({"error": f"Villa '{villa_name}' not found"}, status_code=404)

    timeline = _timelines.get(villa_name)
    records = []
    if timeline:
        for r in timeline.records:
            records.append({
                "start": r.start_date.isoformat(),
                "end": r.end_date.isoformat(),
                "confidence": r.confidence,
                "passenger": r.lead_passenger,
                "extras": r.extras,
                "evidence": r.evidence,
                "opportunity": r.opportunity_name,
            })

    return {
        "name": v.name,
        "capacity": v.capacity,
        "locations": v.locations,
        "area": v.area,
        "bedrooms": v.bedrooms,
        "bathrooms": v.bathrooms,
        "attributes": v.attributes,
        "resital_url": v.resital_url,
        "solmar_url": v.solmar_url,
        "occupancies": records,
    }


@app.get("/api/calendar/{villa_name}")
def get_calendar(
    villa_name: str,
    year: int = Query(default_factory=lambda: date.today().year),
    month: int = Query(default_factory=lambda: date.today().month, ge=1, le=12),
):
    """Get a monthly calendar grid for a villa."""
    _ensure_loaded()
    timeline = _timelines.get(villa_name)
    today = date.today()

    cal = build_month_grid(villa_name, year, month, timeline, today)

    weeks_data = []
    for week in cal.weeks:
        week_data = []
        for day in week:
            week_data.append({
                "day": day.day,
                "date": day.date_obj.isoformat() if day.date_obj else None,
                "is_padding": day.is_padding,
                "is_today": day.is_today,
                "is_past": day.is_past,
                "status": day.status,
                "label": day.label,
                "is_turnover": day.is_turnover,
                "has_checkin": day.has_checkin,
                "has_checkout": day.has_checkout,
                "checkout_confidence": day.checkout_confidence,
                "checkin_confidence": day.checkin_confidence,
                "checkout_passenger": day.checkout_passenger,
                "checkin_passenger": day.checkin_passenger,
                "occupants": [
                    {
                        "passenger": r.lead_passenger,
                        "confidence": r.confidence,
                        "start": r.start_date.isoformat(),
                        "end": r.end_date.isoformat(),
                    }
                    for r in day.occupancy
                ],
            })
        weeks_data.append(week_data)

    return {
        "villa_name": villa_name,
        "year": year,
        "month": month,
        "month_name": cal.month_name,
        "weeks": weeks_data,
    }


@app.get("/api/search")
def search_availability(
    check_in: str = Query(..., description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query(..., description="Check-out date (YYYY-MM-DD)"),
    persons: int = Query(1, ge=0, description="Number of persons"),
    allow_sequences: bool = Query(False, description="Include multi-villa sequences"),
    min_stay: int = Query(2, ge=1, description="Minimum nights per segment"),
    max_splits: int = Query(3, ge=1, le=5, description="Maximum villas in sequence"),
    locations: list[str] = Query([], description="Preferred locations (can be repeated)"),
):
    """Search for available villas for a date range.

    The `locations` parameter can be passed multiple times:
        /api/search?...&locations=Kalkan&locations=Kördere
    When empty, all locations are included.
    """
    _ensure_loaded()

    try:
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
    except ValueError:
        return JSONResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status_code=400)

    if ci >= co:
        return JSONResponse({"error": "Check-in must be before check-out."}, status_code=400)

    total_nights = (co - ci).days

    preferred = locations if locations else None

    # Single villa search
    singles = []
    if _registry:
        results = find_available_villas(
            _registry, _timelines, ci, co,
            persons=persons, preferred_locations=preferred,
        )
        for r in results:
            singles.append({
                "name": r.villa.name,
                "capacity": r.villa.capacity,
                "locations": r.villa.locations,
                "area": r.villa.area,
                "bedrooms": r.villa.bedrooms,
                "attributes": r.villa.attributes,
                "resital_url": r.villa.resital_url,
                "solmar_url": r.villa.solmar_url,
                "is_available": r.is_available,
                "is_flagged": r.is_flagged,
                "status": r.status,
                "reason": r.reason,
                "blocking": [
                    {"start": rec.start_date.isoformat(), "end": rec.end_date.isoformat(),
                     "passenger": rec.lead_passenger, "confidence": rec.confidence}
                    for rec in r.blocking_records
                ],
                "ambiguous": [
                    {"start": rec.start_date.isoformat(), "end": rec.end_date.isoformat(),
                     "passenger": rec.lead_passenger, "evidence": rec.evidence[:100]}
                    for rec in r.ambiguous_records
                ],
            })

    # Sequence search
    sequences = []
    if allow_sequences and _registry:
        seqs = find_sequences(
            _registry, _timelines, ci, co,
            persons=persons, min_stay=min_stay, max_splits=max_splits,
            preferred_locations=preferred, max_results=10,
        )
        for seq in seqs:
            sequences.append({
                "score": round(seq.score(preferred), 1),
                "num_moves": seq.num_moves,
                "total_nights": seq.total_nights,
                "same_region_count": seq.same_region_count,
                "segments": [
                    {
                        "villa": s.villa.name,
                        "locations": s.villa.locations,
                        "capacity": s.villa.capacity,
                        "start": s.start.isoformat(),
                        "end": s.end.isoformat(),
                        "nights": s.nights,
                    }
                    for s in seq.segments
                ],
                "format": seq.format(),
            })

    return {
        "query": {
            "check_in": check_in,
            "check_out": check_out,
            "persons": persons,
            "nights": total_nights,
            "locations": locations,
        },
        "single_villas": singles,
        "sequences": sequences,
        "stats": {
            "available": sum(1 for s in singles if s["is_available"] and not s["is_flagged"]),
            "flagged": sum(1 for s in singles if s["is_available"] and s["is_flagged"]),
            "unavailable": sum(1 for s in singles if not s["is_available"]),
            "sequences": len(sequences),
        },
    }


@app.get("/api/overview")
def overview(
    year: int = Query(default_factory=lambda: date.today().year),
    month: int = Query(default_factory=lambda: date.today().month, ge=1, le=12),
):
    """Daily occupancy overview for all villas in a month."""
    _ensure_loaded()
    import calendar as cal_mod

    num_days = cal_mod.monthrange(year, month)[1]

    daily_data = []
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        d_end = d + timedelta(days=1)

        occupied = []
        free = []

        for villa_name, timeline in _timelines.items():
            blocking = timeline.get_blocking_records(d, d_end)
            if blocking:
                occupied.append({
                    "villa": villa_name,
                    "passengers": [r.lead_passenger for r in blocking],
                })
            else:
                free.append(villa_name)

        daily_data.append({
            "date": d.isoformat(),
            "day": day,
            "weekday": cal_mod.weekday(year, month, day),
            "occupied_count": len(occupied),
            "free_count": len(free),
            "occupancy_pct": round(len(occupied) / max(len(occupied) + len(free), 1) * 100),
            "occupied": occupied,
            "free": free[:10],  # Limit free list
        })

    return {
        "year": year,
        "month": month,
        "month_name": cal_mod.month_name[month],
        "days": daily_data,
    }


@app.get("/api/tags")
def get_tags():
    """Get available location and attribute tags."""
    import json
    tags_path = os.path.join(_get_data_dir(), "tags.json")
    try:
        with open(tags_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"locations": [], "attributes": []}


@app.get("/api/stats")
def stats():
    """Get occupancy classification statistics."""
    _ensure_loaded()
    summary = get_occupancy_summary(_timelines) if _timelines else {}
    return {
        "snapshots_loaded": len(_snapshot_dates),
        "snapshot_range": {
            "first": _snapshot_dates[0].isoformat() if _snapshot_dates else None,
            "last": _snapshot_dates[-1].isoformat() if _snapshot_dates else None,
        },
        "occupancy": {
            "total": summary.get("total_records", 0),
            "confirmed": summary.get("confirmed", 0),
            "likely_active": summary.get("likely_active", 0),
            "ambiguous": summary.get("ambiguous", 0),
            "deleted": summary.get("deleted", 0),
        },
        "villas_tracked": len(_timelines),
        "villas_registered": len(_registry) if _registry else 0,
    }


# ── Durum (Status Overview) ────────────────────────────────────────────────────

@app.get("/api/durum")
def durum():
    """Get current villa status overview — available now + first availability for occupied.

    Returns per-villa: status (available/occupied), free_until or occupied_until,
    next booking or current guest info.
    """
    _ensure_loaded()
    today = date.today()

    result = []
    for villa_name in sorted(_timelines.keys()):
        timeline = _timelines.get(villa_name)
        meta = _registry.get(villa_name) if _registry else None

        # Get blocking records (confirmed + likely_active) sorted by start
        blocking = sorted(
            [r for r in timeline.records if r.is_blocking],
            key=lambda r: r.start_date,
        )

        # Find record that covers today
        current = None
        for r in blocking:
            if r.start_date <= today < r.end_date:
                current = r
                break

        if current:
            # Occupied — find when it frees up
            status = "occupied"
            occupied_until = current.end_date
            current_guest = current.lead_passenger or ""
            current_extras = current.extras or ""

            entry = {
                "name": villa_name,
                "status": status,
                "occupied_until": occupied_until.isoformat(),
                "current_guest": current_guest,
                "current_extras": current_extras,
                "confidence": current.confidence,
            }
        else:
            # Available — find next booking
            future = [r for r in blocking if r.start_date >= today]
            future.sort(key=lambda r: r.start_date)
            next_booking = future[0] if future else None

            entry = {
                "name": villa_name,
                "status": "available",
                "free_until": next_booking.start_date.isoformat() if next_booking else None,
                "free_indefinitely": next_booking is None,
                "next_booking": {
                    "start": next_booking.start_date.isoformat(),
                    "end": next_booking.end_date.isoformat(),
                    "passenger": next_booking.lead_passenger or "",
                    "confidence": next_booking.confidence,
                } if next_booking else None,
            }

        # Villa metadata
        if meta:
            entry["capacity"] = meta.capacity
            entry["locations"] = meta.locations
            entry["area"] = meta.area
            entry["bedrooms"] = meta.bedrooms
            entry["bathrooms"] = meta.bathrooms
            entry["attributes"] = meta.attributes
            entry["resital_url"] = meta.resital_url or ""
            entry["solmar_url"] = meta.solmar_url or ""

        result.append(entry)

    # Sort: available first (by free_until), then occupied (by occupied_until)
    available = sorted(
        [r for r in result if r["status"] == "available"],
        key=lambda r: r.get("free_until") or "9999",
    )
    occupied = sorted(
        [r for r in result if r["status"] == "occupied"],
        key=lambda r: r.get("occupied_until", ""),
    )

    return {
        "date": today.isoformat(),
        "total_villas": len(result),
        "available_count": len(available),
        "occupied_count": len(occupied),
        "available": available,
        "occupied": occupied,
    }


# ── Report Generation Endpoints ──────────────────────────────────────────────

@app.get("/api/reports/weekly")
def api_weekly_report():
    """Generate and download the weekly caretaker report."""
    _ensure_loaded()
    from villa_matcher.reports.generator import weekly_report
    from villa_matcher.reports.file_utils import select_first_file_with_extension

    excel = select_first_file_with_extension(".xlsx", _snapshots_dir)
    if not excel:
        return JSONResponse({"error": "No Excel file found"}, status_code=404)
    ct_path = os.path.join(os.path.dirname(_villas_json), "caretakers.json")
    if not os.path.exists(ct_path):
        ct_path = os.path.join(os.path.dirname(_villas_json), "..", "inputs", "caretakers.json")
    if not os.path.exists(ct_path):
        ct_path = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/caretakers.json"

    report = weekly_report(
        excel,
        ct_path,
        manual_reservations_path=_manual_reservations_json,
    )
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(report, media_type="text/plain; charset=utf-8")


@app.get("/api/reports/ismet")
def api_ismet_report():
    """Generate and download the İsmet Abi report (welcome pack + pool heating)."""
    from villa_matcher.reports.generator import ismet_abi_report
    df = ismet_abi_report(_snapshots_dir)
    if df.empty:
        return JSONResponse({"error": "No reservations found"}, status_code=404)
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    from fastapi.responses import Response
    return Response(buf.read(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=ismet_abi_report.xlsx"})


@app.get("/api/reports/hamdi")
def api_hamdi_report():
    """Generate and download the Hamdi Abi report (unassigned villas)."""
    from villa_matcher.reports.generator import hamdi_abi_report
    inputs = os.path.dirname(_snapshots_dir)
    ct = os.path.join(os.path.dirname(_villas_json), "caretakers.json")
    if not os.path.exists(ct):
        ct = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/caretakers.json"
    report = hamdi_abi_report(inputs, ct)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(report, media_type="text/plain; charset=utf-8")


@app.get("/api/reports/korsan")
def api_korsan_report():
    """Generate and download the Korsan Villas calendar Excel workbook."""
    from villa_matcher.reports.generator import korsan_villas_report
    from villa_matcher.reports.file_utils import select_first_file_with_extension

    excel = select_first_file_with_extension(".xlsx", _snapshots_dir)
    kv_json = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/korsan_villas.json"
    template = "/home/yusuf/Masaüstü/Resital Villa Scripts/Korsan-Villas-Template.xlsx"
    if not excel or not os.path.exists(template):
        return JSONResponse({"error": "Missing Excel or template file"}, status_code=404)

    wb = korsan_villas_report(excel, kv_json, template)
    import io
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from fastapi.responses import Response
    return Response(buf.read(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=korsan_villas.xlsx"})


@app.get("/api/reports/total")
def api_total_report():
    """Generate and download the total history report."""
    from villa_matcher.reports.generator import total_history_report
    df = total_history_report(_snapshots_dir)
    if df.empty:
        return JSONResponse({"error": "No reservations found"}, status_code=404)
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    from fastapi.responses import Response
    return Response(buf.read(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=total_history.xlsx"})


@app.get("/api/reports/gaps")
def api_gaps_report(
    start: str = Query(None, description="Range start (YYYY-MM-DD), default: today"),
    end: str = Query(None, description="Range end (YYYY-MM-DD), default: today + 90 days"),
):
    """List available gaps (free intervals) per villa between a date range.

    Returns plain text formatted as:
        Villa Name
        dd/mm/yy   dd/mm/yy
        dd/mm/yy   dd/mm/yy
    """
    _ensure_loaded()
    from datetime import timedelta

    today = date.today()
    try:
        range_start = date.fromisoformat(start) if start else today
        range_end = date.fromisoformat(end) if end else (today + timedelta(days=90))
    except ValueError:
        return JSONResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status_code=400)

    if range_start >= range_end:
        return JSONResponse({"error": "Start must be before end."}, status_code=400)

    lines = []
    for villa_name in sorted(_timelines.keys()):
        timeline = _timelines[villa_name]
        # Get blocking records that overlap the range
        blocking = [
            r for r in timeline.records
            if r.is_blocking and r.overlaps(range_start, range_end)
        ]
        blocking.sort(key=lambda r: r.start_date)

        # Find free gaps
        gaps = []
        cursor = range_start
        for rec in blocking:
            if rec.start_date > cursor:
                gaps.append((cursor, rec.start_date))
            if rec.end_date > cursor:
                cursor = rec.end_date
        if cursor < range_end:
            gaps.append((cursor, range_end))

        if not gaps:
            continue  # No free gaps for this villa

        lines.append(villa_name)
        for g_start, g_end in gaps:
            lines.append(f"{g_start.strftime('%d/%m/%Y')}   {g_end.strftime('%d/%m/%Y')}")
        lines.append("")  # blank line between villas

    from fastapi.responses import PlainTextResponse as PTR
    if not lines:
        return PTR("No available gaps found in the specified range.",
                   media_type="text/plain; charset=utf-8")

    return PTR("\n".join(lines), media_type="text/plain; charset=utf-8")


@app.post("/api/rebuild")
def api_rebuild():
    """Force rebuild of occupancy timelines from snapshots (called on new data)."""
    global _timelines, _snapshot_dates, _registry, _manual_records
    try:
        _registry = load_villa_registry(_villas_json)
    except FileNotFoundError:
        _registry = None
    try:
        _manual_records = load_manual_reservations(_manual_reservations_json)
    except Exception:
        _manual_records = []
    try:
        _timelines, _snapshot_dates = build_occupancy_timelines(
            _snapshots_dir, manual_records=_manual_records
        )
        summary = get_occupancy_summary(_timelines)
        return {"status": "ok", "snapshots": len(_snapshot_dates), "records": summary["total_records"]}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/upload-snapshot")
async def upload_snapshot(file: UploadFile = File(...)):
    """Upload a Resort Report .xlsx file to the snapshots directory and trigger rebuild."""
    global _timelines, _snapshot_dates, _manual_records, _registry

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return JSONResponse(
            {"status": "error", "message": "Only .xlsx files are accepted."},
            status_code=400,
        )

    snap_dir = _get_snapshots_dir()
    os.makedirs(snap_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"uploaded_{timestamp}_{file.filename}"
    dest_path = os.path.join(snap_dir, safe_name)

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": f"Failed to save file: {e}"},
            status_code=500,
        )

    # Rebuild timelines
    try:
        _registry = load_villa_registry(_villas_json)
    except FileNotFoundError:
        _registry = None
    try:
        _manual_records = load_manual_reservations(_manual_reservations_json)
    except Exception:
        _manual_records = []

    try:
        _timelines, _snapshot_dates = build_occupancy_timelines(
            snap_dir, manual_records=_manual_records
        )
        summary = get_occupancy_summary(_timelines)
        return {
            "status": "ok",
            "filename": safe_name,
            "snapshots": len(_snapshot_dates),
            "records": summary["total_records"],
        }
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": f"Rebuild failed: {e}"},
            status_code=500,
        )


# ── Manual Reservation Endpoints ─────────────────────────────────────────────

@app.get("/api/manual-reservations")
def get_manual_reservations():
    """Get all manual reservations as raw dicts."""
    try:
        data = load_manual_reservations_raw(_manual_reservations_json)
        return {"reservations": data, "total": len(data)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/manual-reservations")
def add_manual_reservation(
    villa: str = Query(..., description="Villa name"),
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    passenger: str = Query("", description="Lead passenger name"),
    extras: str = Query("", description="Extras (comma-separated)"),
    notes: str = Query("", description="Free-text notes"),
):
    """Add a new manual reservation and rebuild timelines."""
    global _timelines, _snapshot_dates, _manual_records

    # Validate dates
    from datetime import date as date_type
    try:
        ci = date_type.fromisoformat(start)
        co = date_type.fromisoformat(end)
    except ValueError:
        return JSONResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status_code=400)

    if ci >= co:
        return JSONResponse({"error": "Check-in must be before check-out."}, status_code=400)

    # Validate villa exists
    _ensure_loaded()
    if _registry and villa not in _registry:
        return JSONResponse({"error": f"Villa '{villa}' not found in registry."}, status_code=404)

    # Append to JSON file
    try:
        existing = load_manual_reservations_raw(_manual_reservations_json)
    except Exception:
        existing = []

    entry = {
        "villa": villa,
        "start": start,
        "end": end,
        "passenger": passenger,
        "extras": extras,
        "notes": notes,
    }
    existing.append(entry)
    save_manual_reservations(_manual_reservations_json, existing)

    # Rebuild timelines with new manual reservation
    try:
        _manual_records = load_manual_reservations(_manual_reservations_json)
        _timelines, _snapshot_dates = build_occupancy_timelines(
            _snapshots_dir, manual_records=_manual_records
        )
    except Exception:
        pass

    return {"status": "ok", "entry": entry, "total": len(existing)}


@app.delete("/api/manual-reservations/{index}")
def delete_manual_reservation(index: int):
    """Delete a manual reservation by array index and rebuild timelines."""
    global _timelines, _snapshot_dates, _manual_records

    try:
        existing = load_manual_reservations_raw(_manual_reservations_json)
    except Exception:
        return JSONResponse({"error": "No manual reservations file found."}, status_code=404)

    if index < 0 or index >= len(existing):
        return JSONResponse({"error": f"Index {index} out of range (0—{len(existing)-1})."}, status_code=404)

    removed = existing.pop(index)
    save_manual_reservations(_manual_reservations_json, existing)

    # Rebuild timelines without the removed reservation
    try:
        _manual_records = load_manual_reservations(_manual_reservations_json)
        _timelines, _snapshot_dates = build_occupancy_timelines(
            _snapshots_dir, manual_records=_manual_records
        )
    except Exception:
        pass

    return {"status": "ok", "removed": removed, "total": len(existing)}


@app.put("/api/manual-reservations/{index}")
def update_manual_reservation(
    index: int,
    villa: str = Query(..., description="Villa name"),
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    passenger: str = Query("", description="Lead passenger name"),
    extras: str = Query("", description="Extras (comma-separated)"),
    notes: str = Query("", description="Free-text notes"),
):
    """Update an existing manual reservation by index and rebuild timelines."""
    global _timelines, _snapshot_dates, _manual_records

    from datetime import date as date_type
    try:
        ci = date_type.fromisoformat(start)
        co = date_type.fromisoformat(end)
    except ValueError:
        return JSONResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status_code=400)

    if ci >= co:
        return JSONResponse({"error": "Check-in must be before check-out."}, status_code=400)

    try:
        existing = load_manual_reservations_raw(_manual_reservations_json)
    except Exception:
        return JSONResponse({"error": "No manual reservations file found."}, status_code=404)

    if index < 0 or index >= len(existing):
        return JSONResponse({"error": f"Index {index} out of range (0—{len(existing)-1})."}, status_code=404)

    existing[index] = {
        "villa": villa,
        "start": start,
        "end": end,
        "passenger": passenger,
        "extras": extras,
        "notes": notes,
    }
    save_manual_reservations(_manual_reservations_json, existing)

    try:
        _manual_records = load_manual_reservations(_manual_reservations_json)
        _timelines, _snapshot_dates = build_occupancy_timelines(
            _snapshots_dir, manual_records=_manual_records
        )
    except Exception:
        pass

    return {"status": "ok", "entry": existing[index], "total": len(existing)}


# ── Static frontend ──────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def index():
    """Serve the single-page frontend."""
    return FileResponse(str(_STATIC_DIR / "index.html"))


# Mount static files at the end so API routes take precedence
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
