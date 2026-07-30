"""CLI entry point for villa-matcher.

Commands:
    villa-matcher rebuild    — Load all snapshots, build occupancy timelines
    villa-matcher analyze    — Show occupancy classification summary
    villa-matcher find       — Find available villas for a date range
    villa-matcher calendar   — Interactive terminal calendar
    villa-matcher overview   — Month overview across all villas
    villa-matcher status     — Show timeline for a specific villa
    villa-matcher serve      — Start the web UI (FastAPI at localhost:8080)
"""

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from villa_matcher.engine.matcher import find_available_villas
from villa_matcher.engine.occupancy import (
    build_occupancy_timelines,
    get_occupancy_summary,
)
from villa_matcher.engine.sequence import find_sequences
from villa_matcher.io.villa_registry import create_template_registry, load_villa_registry
from villa_matcher.io.manual_reservations import load_manual_reservations
from villa_matcher.models.snapshot import OccupancyTimeline
from villa_matcher.utils.dates import parse_date

app = typer.Typer(
    name="villa-matcher",
    help="Villa availability matcher with multi-snapshot occupancy detection",
    add_completion=False,
)

console = Console()

# ── Default paths ────────────────────────────────────────────────────────────

def _get_data_dir() -> str:
    """Get the data directory relative to this package."""
    pkg_dir = Path(__file__).resolve().parent.parent
    return str(pkg_dir / "data")


def _get_snapshots_dir() -> str:
    """Get the snapshots directory, checking for the symlink."""
    data_dir = Path(_get_data_dir())
    snapshots = data_dir / "all_reservations"

    # Check if it's a valid directory with files
    if snapshots.is_dir():
        import os as _os
        xlsx_files = [f for f in _os.listdir(str(snapshots)) if f.endswith(".xlsx")]
        if xlsx_files:
            return str(snapshots)

    # Fall back to the original Resital Villa Scripts location
    legacy = Path("/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/all_reservations")
    if legacy.is_dir():
        return str(legacy)

    return str(snapshots)  # Return the symlink path even if empty


# ── Rebuild command ──────────────────────────────────────────────────────────

@app.command()
def rebuild(
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", "-s", help="Directory containing Resort Report .xlsx files"
    ),
) -> None:
    """Rebuild occupancy timelines from all report snapshots.

    Loads every .xlsx file in the snapshots directory, classifies each
    reservation using the multi-snapshot lifecycle rules, and prints
    a summary of the results.
    """
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    console.print(f"[bold]Loading snapshots from:[/] {snapshots_dir}")

    try:
        timelines, snapshot_dates = build_occupancy_timelines(snapshots_dir)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]Loaded {len(snapshot_dates)} snapshots[/]")
    console.print(f"[green]Built timelines for {len(timelines)} villas[/]")

    # Print summary
    summary = get_occupancy_summary(timelines)

    table = Table(title="Occupancy Classification Summary")
    table.add_column("Classification", style="cyan")
    table.add_column("Count", style="bold", justify="right")

    table.add_row("Confirmed", str(summary["confirmed"]))
    table.add_row("Likely Active", str(summary["likely_active"]))
    table.add_row("Ambiguous", str(summary["ambiguous"]))
    table.add_row("Deleted", str(summary["deleted"]))
    table.add_row("[bold]Total[/]", f"[bold]{summary['total_records']}[/]")

    console.print(table)

    # Show likely_active and ambiguous for review
    if summary["likely_active"] > 0 or summary["ambiguous"] > 0:
        console.print("\n[yellow]Records needing attention:[/]")
        for villa_name, timeline in timelines.items():
            for record in timeline.records:
                if record.confidence in ("likely_active", "ambiguous"):
                    console.print(
                        f"  [{CONFIDENCE_COLORS[record.confidence]}]"
                        f"{record.confidence}[/] — {villa_name}: "
                        f"{record.start_date} → {record.end_date}"
                        f" ({record.lead_passenger or record.opportunity_name[:20]})"
                    )

# ── Analyze command ───────────────────────────────────────────────────────────

@app.command()
def analyze(
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", "-s", help="Directory containing Resort Report .xlsx files"
    ),
    show_ambiguous: bool = typer.Option(
        False, "--show-ambiguous", "-a", help="Show all ambiguous records with evidence"
    ),
) -> None:
    """Analyze snapshot data and show occupancy classification details."""
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    console.print(f"[bold]Analyzing snapshots in:[/] {snapshots_dir}")

    timelines, snapshot_dates = build_occupancy_timelines(snapshots_dir)
    summary = get_occupancy_summary(timelines)

    # Per-villa breakdown
    table = Table(title="Per-Villa Occupancy Breakdown")
    table.add_column("Villa", style="cyan")
    table.add_column("Confirmed", justify="right")
    table.add_column("Likely", justify="right")
    table.add_column("Ambiguous", justify="right")
    table.add_column("Deleted", justify="right")
    table.add_column("Total", justify="right", style="bold")

    for villa_name in sorted(summary["villa_details"].keys()):
        vd = summary["villa_details"][villa_name]
        table.add_row(
            villa_name,
            str(vd["confirmed"]),
            str(vd["likely_active"]),
            str(vd["ambiguous"]),
            str(vd["deleted"]),
            str(vd["total"]),
        )

    console.print(table)

    # Snapshot date range
    console.print(f"\n[dim]Snapshot date range: {snapshot_dates[0]} → {snapshot_dates[-1]}[/]")
    console.print(f"[dim]Total snapshots: {len(snapshot_dates)}[/]")

    if show_ambiguous:
        console.print("\n[yellow]Ambiguous & Likely-Active Records:[/]")
        for villa_name, timeline in timelines.items():
            for record in timeline.records:
                if record.confidence in ("likely_active", "ambiguous"):
                    color = CONFIDENCE_COLORS[record.confidence]
                    console.print(
                        f"  [{color}]{record.confidence}[/] {villa_name}: "
                        f"{record.start_date} → {record.end_date}"
                    )
                    console.print(f"    [dim]{record.evidence}[/]")

# ── Find command ──────────────────────────────────────────────────────────────

CONFIDENCE_COLORS = {
    "confirmed": "green",
    "likely_active": "yellow",
    "ambiguous": "red",
    "deleted": "dim",
}


@app.command()
def find(
    check_in: str = typer.Option(
        ..., "--from", "-f", help="Check-in date (YYYY-MM-DD)"
    ),
    check_out: str = typer.Option(
        ..., "--to", "-t", help="Check-out date (YYYY-MM-DD)"
    ),
    persons: int = typer.Option(1, "--persons", "-p", help="Number of persons"),
    allow_sequences: bool = typer.Option(
        False, "--allow-sequences", "-s", help="Also search for multi-villa sequences"
    ),
    min_stay: int = typer.Option(2, "--min-stay", help="Minimum nights per villa segment"),
    max_splits: int = typer.Option(3, "--max-splits", help="Maximum number of villas in a sequence"),
    preferred_locations: list[str] = typer.Option(
        [], "--location", "-l", help="Preferred location/region (can be repeated: -l Kalkan -l Kördere)"
    ),
    villas_json: Optional[str] = typer.Option(
        None, "--villas-json", help="Path to villas.json metadata"
    ),
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", help="Directory containing report snapshots"
    ),
) -> None:
    """Find available villas for a date range.

    Searches for single villas available for the entire period,
    and optionally multi-villa sequences.
    """
    # Parse dates
    try:
        ci = date.fromisoformat(check_in)
    except ValueError:
        console.print(f"[red]Invalid check-in date: {check_in}[/] (use YYYY-MM-DD)")
        raise typer.Exit(code=1)

    try:
        co = date.fromisoformat(check_out)
    except ValueError:
        console.print(f"[red]Invalid check-out date: {check_out}[/] (use YYYY-MM-DD)")
        raise typer.Exit(code=1)

    if ci >= co:
        console.print("[red]Check-in must be before check-out.[/]")
        raise typer.Exit(code=1)

    total_nights = (co - ci).days

    # Load data
    if villas_json is None:
        villas_json = os.path.join(_get_data_dir(), "villas.json")
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    try:
        registry = load_villa_registry(villas_json)
    except FileNotFoundError:
        console.print(f"[yellow]Villa registry not found at {villas_json}[/]")
        console.print("[yellow]Run 'villa-matcher rebuild' first, or create data/villas.json[/]")
        raise typer.Exit(code=1)

    # Load manual reservations if available
    manual_path = os.path.join(_get_data_dir(), "manual_reservations.json")
    manual_records = []
    try:
        manual_records = load_manual_reservations(manual_path)
        if manual_records:
            console.print(f"[dim]Loaded {len(manual_records)} manual reservation(s)[/]")
    except Exception:
        pass

    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir, manual_records=manual_records)
    except FileNotFoundError:
        console.print(f"[yellow]No snapshots found at {snapshots_dir}[/]")
        console.print("[yellow]Proceeding with empty timelines (all villas assumed available)[/]")
        timelines = {}

    # Search
    console.print(f"\n[bold]Searching:[/] {ci} → {co} ({total_nights} nights, {persons} persons)")
    if preferred_locations:
        console.print(f"  Locations: {', '.join(preferred_locations)}")

    locs = preferred_locations if preferred_locations else None

    results = find_available_villas(
        registry,
        timelines,
        ci,
        co,
        persons=persons,
        preferred_locations=locs,
    )

    # Print results
    available = [r for r in results if r.is_available and not r.is_flagged]
    flagged = [r for r in results if r.is_available and r.is_flagged]
    unavailable = [r for r in results if not r.is_available]

    console.print(f"\n[bold green]{len(available)} available[/] | "
                   f"[bold yellow]{len(flagged)} flagged[/] | "
                   f"[bold red]{len(unavailable)} unavailable[/]")

    if available:
        console.print("\n[bold green]✓ Available Villas:[/]")
        for r in available:
            _print_villa_result(r)

    if flagged:
        console.print("\n[bold yellow]⚠ Available but Flagged (ambiguous records overlap):[/]")
        for r in flagged:
            _print_villa_result(r)

    if not available and not flagged:
        console.print("\n[bold red]No villas available for the full period.[/]")

    # Sequences
    if allow_sequences:
        console.print(f"\n[bold]Searching for multi-villa sequences...[/]")
        sequences = find_sequences(
            registry,
            timelines,
            ci,
            co,
            persons=persons,
            min_stay=min_stay,
            max_splits=max_splits,
            preferred_locations=locs,
            max_results=10,
        )

        if sequences:
            console.print(f"\n[bold cyan]Found {len(sequences)} sequence(s):[/]")
            for i, seq in enumerate(sequences):
                score = seq.score(locs)
                console.print(f"\n  [bold]#{i + 1}[/] [dim](score: {score:.1f})[/]")
                for j, seg in enumerate(seq.segments):
                    arrow = "├─" if j < len(seq.segments) - 1 else "└─"
                    console.print(
                        f"    {arrow} [cyan]{seg.villa.name}[/] "
                        f"{seg.start.strftime('%d/%m')} → {seg.end.strftime('%d/%m')} "
                        f"({seg.nights} nights)"
                    )
                    if seg.villa.locations:
                        console.print(f"     [dim]{', '.join(seg.villa.locations)}[/]")
        else:
            console.print("\n[yellow]No valid sequences found. Try:[/]")
            console.print("  - Increasing --max-splits")
            console.print("  - Reducing --min-stay")
            console.print("  - Checking adjacent dates")

    # If nothing found at all, suggest nearest dates
    if not available and not flagged and (not allow_sequences or not sequences if allow_sequences else True):
        console.print("\n[dim]Tip: Use 'villa-matcher calendar' to browse occupancy visually.[/]")


def _print_villa_result(r) -> None:
    """Print a single VillaAvailability result."""
    extras = []
    if r.villa.locations:
        extras.append(', '.join(r.villa.locations))
    if r.villa.capacity:
        extras.append(f"capacity {r.villa.capacity}")
    if r.villa.area:
        extras.append(r.villa.area)
    extra_str = f" [dim]({', '.join(extras)})[/]" if extras else ""

    status_color = "green" if not r.is_flagged else "yellow"
    console.print(f"  [{status_color}]{r.villa.name}[/]{extra_str}")
    console.print(f"    [dim]{r.reason}[/]")

    if r.ambiguous_records:
        for rec in r.ambiguous_records:
            console.print(
                f"    [yellow]? {rec.start_date} → {rec.end_date} "
                f"({rec.lead_passenger or 'unknown'}) — {rec.evidence[:100]}[/]"
            )


# ── Calendar command ──────────────────────────────────────────────────────────

@app.command()
def calendar(
    villa: Optional[str] = typer.Option(
        None, "--villa", "-v", help="Villa name to display"
    ),
    month: Optional[int] = typer.Option(
        None, "--month", "-m", help="Month (1-12)", min=1, max=12
    ),
    year: Optional[int] = typer.Option(
        None, "--year", "-y", help="Year (e.g. 2026)"
    ),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Launch interactive calendar browser"
    ),
    villas_json: Optional[str] = typer.Option(
        None, "--villas-json", help="Path to villas.json metadata"
    ),
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", help="Directory containing report snapshots"
    ),
) -> None:
    """View villa occupancy calendar.

    Without --interactive, prints a static calendar for one villa/month.
    With --interactive, launches a full-screen browsable calendar.
    """
    if villas_json is None:
        villas_json = os.path.join(_get_data_dir(), "villas.json")
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    try:
        registry = load_villa_registry(villas_json)
    except FileNotFoundError:
        console.print(f"[red]Villa registry not found: {villas_json}[/]")
        raise typer.Exit(code=1)

    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir)
    except FileNotFoundError:
        console.print(f"[yellow]No snapshots found. Showing empty calendar.[/]")
        timelines = {}

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    if interactive:
        from villa_matcher.calendar.terminal import run_interactive_calendar
        run_interactive_calendar(
            registry,
            timelines,
            start_villa=villa,
            start_year=year,
            start_month=month,
        )
    else:
        from villa_matcher.calendar.terminal import print_calendar_static

        if villa is None:
            villa = registry.names[0]
            console.print(f"[dim]No villa specified — showing {villa}. Use --villa to change.[/]\n")

        if villa not in registry:
            console.print(f"[red]Villa '{villa}' not found in registry.[/]")
            console.print(f"Available: {', '.join(registry.names[:10])}...")
            raise typer.Exit(code=1)

        v = registry.get(villa)
        timeline = timelines.get(villa)
        print_calendar_static(villa, year, month, timeline, v)


# ── Overview command ──────────────────────────────────────────────────────────

@app.command()
def overview(
    month: Optional[int] = typer.Option(
        None, "--month", "-m", help="Month (1-12)", min=1, max=12
    ),
    year: Optional[int] = typer.Option(
        None, "--year", "-y", help="Year (e.g. 2026)"
    ),
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", help="Directory containing report snapshots"
    ),
) -> None:
    """Show occupancy overview for all villas in a given month.

    Compact table showing which villas are free/occupied each day.
    """
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir)
    except FileNotFoundError:
        console.print(f"[red]No snapshots found: {snapshots_dir}[/]")
        raise typer.Exit(code=1)

    import calendar as cal_mod
    num_days = cal_mod.monthrange(year, month)[1]

    # Count occupancy per day
    from collections import defaultdict
    daily_occupied: dict[int, set[str]] = defaultdict(set)
    daily_free: dict[int, set[str]] = defaultdict(set)

    for villa_name, timeline in timelines.items():
        for day in range(1, num_days + 1):
            d = date(year, month, day)
            d_end = date(year, month, day) + __import__("datetime").timedelta(days=1)
            blocking = timeline.get_blocking_records(d, d_end)
            if blocking:
                daily_occupied[day].add(villa_name)
            else:
                daily_free[day].add(villa_name)

    # Print as compact table
    console.print(f"\n[bold]Occupancy Overview — {cal_mod.month_name[month]} {year}[/]")
    console.print(f"[dim]{len(timelines)} villas tracked[/]\n")

    table = Table(title="Daily Occupancy")
    table.add_column("Day", style="cyan")
    table.add_column("Occupied", justify="right", style="red")
    table.add_column("Free", justify="right", style="green")
    table.add_column("Occupancy %", justify="right")

    for day in range(1, num_days + 1):
        occupied = len(daily_occupied.get(day, set()))
        free = len(daily_free.get(day, set()))
        total = occupied + free
        pct = (occupied / total * 100) if total > 0 else 0

        bar_len = int(pct / 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        pct_color = "red" if pct > 80 else "yellow" if pct > 50 else "green"

        table.add_row(
            f"{day:2d} {DAY_NAMES_TR[(cal_mod.weekday(year, month, day))]}",
            str(occupied),
            str(free),
            f"[{pct_color}]{bar} {pct:.0f}%[/]",
        )

    console.print(table)

    # Show most occupied days
    most_occupied = sorted(daily_occupied.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    if most_occupied:
        console.print("\n[bold red]Most occupied days:[/]")
        for day, villas in most_occupied:
            console.print(f"  {day:2d}: {', '.join(sorted(villas)[:10])}")


DAY_NAMES_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


# ── Status command ────────────────────────────────────────────────────────────

@app.command()
def status(
    villa: str = typer.Argument(..., help="Villa name to show timeline for"),
    snapshots_dir: Optional[str] = typer.Option(
        None, "--snapshots-dir", help="Directory containing report snapshots"
    ),
) -> None:
    """Show the full occupancy timeline for a specific villa."""
    if snapshots_dir is None:
        snapshots_dir = _get_snapshots_dir()

    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir)
    except FileNotFoundError:
        console.print(f"[red]No snapshots found: {snapshots_dir}[/]")
        raise typer.Exit(code=1)

    if villa not in timelines:
        console.print(f"[yellow]No occupancy data for '{villa}'.[/]")
        similar = [v for v in timelines.keys() if villa.lower() in v.lower()]
        if similar:
            console.print(f"Did you mean: {', '.join(similar)}?")
        raise typer.Exit(code=0)

    timeline = timelines[villa]
    console.print(f"\n[bold]Occupancy Timeline: {villa}[/]")
    console.print(f"[dim]{len(timeline.records)} records[/]\n")

    table = Table()
    table.add_column("Start", style="cyan")
    table.add_column("End", style="cyan")
    table.add_column("Passenger")
    table.add_column("Confidence")
    table.add_column("Evidence")

    for record in timeline.records:
        color = CONFIDENCE_COLORS.get(record.confidence, "white")
        table.add_row(
            record.start_date.isoformat(),
            record.end_date.isoformat(),
            record.lead_passenger or "—",
            f"[{color}]{record.confidence}[/]",
            record.evidence[:120],
        )

    console.print(table)


# ── Init command ──────────────────────────────────────────────────────────────

@app.command()
def init(
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output path for villas.json template"
    ),
) -> None:
    """Create a villas.json template from known villa names.

    Scans the snapshots directory to discover all villa names, then
    creates a template JSON file with empty metadata fields for the
    user to fill in.
    """
    if output is None:
        output = os.path.join(_get_data_dir(), "villas.json")

    snapshots_dir = _get_snapshots_dir()

    # Try to get villa names from snapshots first
    villa_names = set()
    try:
        timelines, _ = build_occupancy_timelines(snapshots_dir)
        villa_names = set(timelines.keys())
    except Exception:
        pass

    # Also pull from legacy sources
    legacy_sources = [
        "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/korsan_villas.json",
        "/home/yusuf/Masaüstü/Resital Villa Scripts/villas.txt",
    ]

    for src in legacy_sources:
        if not os.path.exists(src):
            continue
        try:
            import json
            if src.endswith(".json"):
                with open(src) as f:
                    names = json.load(f)
                    villa_names.update(names)
            else:
                with open(src) as f:
                    for line in f:
                        name = line.strip()
                        if name:
                            villa_names.add(name)
        except Exception:
            pass

    # Also check caretakers.json
    ct_path = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/caretakers.json"
    if os.path.exists(ct_path):
        try:
            import json
            with open(ct_path) as f:
                caretakers = json.load(f)
                for ct in caretakers:
                    villa_names.update(ct.get("assignments", {}).keys())
        except Exception:
            pass

    if not villa_names:
        console.print("[red]No villa names discovered. Create data/villas.json manually.[/]")
        raise typer.Exit(code=1)

    create_template_registry(sorted(villa_names), output)
    console.print(f"[green]Created villa registry template:[/] {output}")
    console.print(f"[dim]{len(villa_names)} villas — fill in capacity, location, area, attributes[/]")


# ── Serve command ────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8080, "--port", "-p", help="Port to listen on"),
) -> None:
    """Start the web UI server.

    Launches a FastAPI server with an interactive villa calendar,
    availability search, and multi-villa sequence finder.
    Open http://localhost:8080 in your browser.
    """
    import uvicorn
    from villa_matcher.web.app import app as web_app

    console.print(f"\n[bold cyan]🏠 Villa Matcher Web UI[/]")
    console.print(f"[dim]Starting server at http://localhost:{port}[/]")
    console.print(f"[dim]Press Ctrl+C to stop[/]\n")

    uvicorn.run(web_app, host=host, port=port, log_level="info")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
