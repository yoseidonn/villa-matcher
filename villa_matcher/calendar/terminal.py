"""Interactive terminal calendar widget using Rich.

Provides a full-screen interactive calendar for browsing villa occupancy.
Navigation: arrow keys for villa/month, 'f' to find availability, 'q' to quit.
"""

from datetime import date

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from villa_matcher.calendar.render import (
    CalendarMonth,
    build_month_grid,
    get_navigation_months,
)
from villa_matcher.models.snapshot import OccupancyTimeline
from villa_matcher.models.villa import Villa, VillaRegistry


# ── Styling ──────────────────────────────────────────────────────────────────

DAY_NAMES_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

CONFIDENCE_COLORS = {
    "confirmed": "green",
    "likely_active": "yellow",
    "ambiguous": "red",
    "free": "white",
    "empty": "rgb(60,60,60)",
}

CONFIDENCE_CHARS = {
    "confirmed": "■",
    "likely_active": "▓",
    "ambiguous": "?",
    "free": " ",
    "empty": " ",
}

CONFIDENCE_LABELS = {
    "confirmed": "■ Confirmed",
    "likely_active": "▓ Likely active (guest probably there)",
    "ambiguous": "? Ambiguous (needs review)",
    "free": "  Free / Available",
}


def _render_month(
    cal: CalendarMonth,
    villa: Villa | None = None,
) -> Panel:
    """Render a single month grid as a Rich Panel."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
        expand=True,
        box=None,
    )

    # Header: day names
    for day_name in DAY_NAMES_TR:
        table.add_column(day_name, justify="center", width=8, no_wrap=True)

    # Rows: weeks
    for week in cal.weeks:
        row_cells = []
        for day in week:
            if day.is_padding:
                row_cells.append(Text("", style="dim"))
            else:
                status = day.status
                color = CONFIDENCE_COLORS.get(status, "white")
                char = CONFIDENCE_CHARS.get(status, " ")

                cell_text = Text()
                # Day number
                day_style = "bold" if day.is_today else ""
                if day.is_today:
                    day_style += " underline"
                cell_text.append(f"{day.day:2d}", style=f"{color} {day_style}")

                # Occupancy indicator
                if status != "free":
                    cell_text.append(f" {char}", style=f"bold {color}")

                # Passenger label on second line (if available)
                label = day.label
                if label:
                    cell_text.append(f"\n{label}", style=f"{color} italic")

                row_cells.append(cell_text)

        table.add_row(*row_cells)

    # Build title
    title_parts = [f"Villa {cal.villa_name} — {cal.month_name} {cal.year}"]
    if villa:
        extras = []
        if villa.capacity:
            extras.append(f"Capacity: {villa.capacity}")
        if villa.locations:
            extras.append(f"Locations: {', '.join(villa.locations)}")
        if villa.area:
            extras.append(f"Area: {villa.area}")
        if extras:
            title_parts.append(" | ".join(extras))

    return Panel(
        table,
        title="\n".join(title_parts),
        border_style="cyan",
    )


def _render_legend() -> Panel:
    """Render the occupancy color legend."""
    text = Text()
    for i, (label, desc) in enumerate(CONFIDENCE_LABELS.items()):
        if i > 0:
            text.append("\n")
        color = CONFIDENCE_COLORS.get(label, "white")
        char = CONFIDENCE_CHARS.get(label, " ")
        text.append(f"{char} ", style=f"bold {color}")
        text.append(desc, style="dim")
    return Panel(text, title="Legend", border_style="dim")


def _render_villa_list(
    villas: list[str],
    current_index: int,
) -> Panel:
    """Render a scrollable villa list sidebar."""
    text = Text()
    for i, name in enumerate(villas):
        if i > 0:
            text.append("\n")
        if i == current_index:
            text.append(f"▶ {name}", style="bold cyan reverse")
        else:
            text.append(f"  {name}", style="dim")
    return Panel(text, title=f"Villas ({len(villas)})", border_style="dim")


def _render_controls() -> Panel:
    """Render the keyboard controls help."""
    text = Text()
    text.append("← →  ", style="bold cyan")
    text.append("Change month\n", style="dim")
    text.append("↑ ↓  ", style="bold cyan")
    text.append("Change villa\n", style="dim")
    text.append("f    ", style="bold cyan")
    text.append("Find availability\n", style="dim")
    text.append("q    ", style="bold cyan")
    text.append("Quit", style="dim")
    return Panel(text, title="Controls", border_style="dim")


def _render_reservations(
    cal: CalendarMonth,
    timeline: OccupancyTimeline | None,
) -> Panel:
    """Render the reservation list for this villa/month."""
    text = Text()

    if timeline is None or not timeline.records:
        text.append("No known reservations", style="dim italic")
        return Panel(text, title="Reservations this month", border_style="dim")

    # Filter records that overlap this month
    import calendar as cal_mod

    num_days = cal_mod.monthrange(cal.year, cal.month)[1]
    month_start = date(cal.year, cal.month, 1)
    month_end = date(cal.year, cal.month, num_days)

    shown = 0
    for record in timeline.records:
        if record.confidence == "deleted":
            continue
        if record.start_date <= month_end and record.end_date > month_start:
            if shown > 0:
                text.append("\n")

            color = CONFIDENCE_COLORS.get(record.confidence, "white")
            char = CONFIDENCE_CHARS.get(record.confidence, " ")

            start_str = record.start_date.strftime("%d %b")
            end_str = record.end_date.strftime("%d %b")

            text.append(f"{char} ", style=f"bold {color}")
            text.append(f"{start_str} — {end_str}  ", style="white")
            if record.lead_passenger:
                text.append(f"{record.lead_passenger}", style=f"bold {color}")
            text.append(f"\n  [{record.confidence}] {record.evidence[:80]}...", style="dim italic")
            shown += 1

    if shown == 0:
        text.append("No reservations this month", style="dim")

    return Panel(text, title=f"Reservations ({shown})", border_style="dim")


def run_interactive_calendar(
    registry: VillaRegistry,
    timelines: dict[str, OccupancyTimeline],
    start_villa: str | None = None,
    start_year: int | None = None,
    start_month: int | None = None,
) -> None:
    """Run the full-screen interactive calendar browser.

    This is a blocking call that runs until the user presses 'q'.

    Args:
        registry: Villa metadata.
        timelines: Occupancy timelines per villa.
        start_villa: Initial villa to show.
        start_year, start_month: Initial month to show.
    """
    villa_names = registry.names
    if not villa_names:
        print("No villas in registry. Run 'villa-matcher rebuild' first.")
        return

    if start_villa and start_villa in villa_names:
        villa_idx = villa_names.index(start_villa)
    else:
        villa_idx = 0

    today = date.today()
    if start_year is None:
        start_year = today.year
    if start_month is None:
        start_month = today.month

    current_year = start_year
    current_month = start_month

    console = Console()
    console.clear()

    def build_layout():
        villa_name = villa_names[villa_idx]
        villa = registry.get(villa_name)
        timeline = timelines.get(villa_name)

        cal = build_month_grid(villa_name, current_year, current_month, timeline, today)

        layout = Layout()
        layout.split_row(
            Layout(name="sidebar", size=24),
            Layout(name="main"),
        )
        layout["sidebar"].split_column(
            Layout(_render_villa_list(villa_names, villa_idx), name="villas", ratio=2),
            Layout(_render_legend(), name="legend", ratio=1),
            Layout(_render_controls(), name="controls", ratio=1),
        )
        layout["main"].split_column(
            Layout(_render_month(cal, villa), name="calendar", ratio=3),
            Layout(_render_reservations(cal, timeline), name="details", ratio=2),
        )
        return layout

    try:
        with Live(build_layout(), console=console, screen=True, auto_refresh=False) as live:
            while True:
                live.update(build_layout(), refresh=True)
                key = _read_key()

                if key == "q":
                    break
                elif key == "left":
                    current_month, current_year = get_navigation_months(current_year, current_month)[0]
                elif key == "right":
                    current_month, current_year = get_navigation_months(current_year, current_month)[1]
                elif key == "up":
                    villa_idx = (villa_idx - 1) % len(villa_names)
                elif key == "down":
                    villa_idx = (villa_idx + 1) % len(villa_names)
                elif key == "f":
                    # Exit interactive mode and let the CLI handle find
                    live.stop()
                    console.clear()
                    console.print("[bold cyan]Find Availability[/]")
                    console.print(f"Current villa: {villa_names[villa_idx]}")
                    console.print(f"Current month: {current_month}/{current_year}")
                    console.print("\nUse [bold]villa-matcher find[/] command for availability search.")
                    console.print("Press Enter to return to calendar...")
                    input()
                    live.start()
                elif key == "home":
                    current_year = today.year
                    current_month = today.month

    except KeyboardInterrupt:
        console.clear()
        return


def _read_key() -> str:
    """Read a single keypress and return a semantic key name."""
    try:
        import readchar

        ch = readchar.readkey()
        if ch == readchar.key.UP:
            return "up"
        elif ch == readchar.key.DOWN:
            return "down"
        elif ch == readchar.key.LEFT:
            return "left"
        elif ch == readchar.key.RIGHT:
            return "right"
        elif ch == readchar.key.ENTER:
            return "enter"
        elif ch == readchar.key.HOME:
            return "home"
        elif ch == readchar.key.ESC:
            return "q"
        else:
            return ch.lower()
    except ImportError:
        import sys
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Escape sequence
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    mapping = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home"}
                    return mapping.get(ch3, "")
                return "q"
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def print_calendar_static(
    villa_name: str,
    year: int,
    month: int,
    timeline: OccupancyTimeline | None,
    villa: Villa | None = None,
) -> None:
    """Print a single month calendar to stdout (non-interactive)."""
    console = Console()
    cal = build_month_grid(villa_name, year, month, timeline)
    panel = _render_month(cal, villa)
    console.print(panel)
    console.print(_render_legend())
