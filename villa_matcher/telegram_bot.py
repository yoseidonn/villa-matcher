"""Telegram bot for Villa Matcher — auto-ingest snapshots + rebuild + villa-finder.

Sends a Resort Report .xlsx file via Telegram → bot saves it to the
snapshots directory and triggers an occupancy rebuild.

/villa-finder — Natural language villa availability search.

Setup:
  1. Create bot via @BotFather on Telegram, get token
  2. export TELEGRAM_BOT_TOKEN=your_token
  3. villa-matcher serve (starts both web + bot)
"""

import os
import re
import asyncio
import logging
from datetime import date, datetime
from pathlib import Path

import httpx

logger = logging.getLogger("villa-matcher.telegram")

# ── Turkish month names ──────────────────────────────────────────────────────

_TR_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3,
    "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "agustos": 8,
    "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_KNOWN_LOCATIONS = [
    "kalkan", "kördere", "kordere", "islamlar", "islamlar", "üzümlü", "uzumlu",
    "kaş", "kas", "dalyan", "akbel", "bezirgan", "gökçeören", "gokceoren",
    "kınık", "kinik", "yeşilköy", "yesilkoy", "çavdır", "cavdir", "fethiye",
    "ölüdeniz", "oludeniz",
]

# ── Config ───────────────────────────────────────────────────────────────────

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SNAPSHOTS_DIR = os.environ.get("SNAPSHOTS_DIR", "")
REBUILD_URL = os.environ.get("REBUILD_URL", "http://localhost:8080/api/rebuild")
ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "")  # comma-separated usernames

if not SNAPSHOTS_DIR:
    legacy = "/home/yusuf/Masaüstü/Resital Villa Scripts/inputs/all_reservations"
    if os.path.isdir(legacy):
        SNAPSHOTS_DIR = legacy
    else:
        SNAPSHOTS_DIR = str(Path(__file__).resolve().parent.parent / "data" / "all_reservations")


# ── NLP Query Parser ──────────────────────────────────────────────────────────

def parse_villa_query(text: str) -> dict:
    """Parse a natural language villa query into structured search params.

    Handles inputs like:
      - "Kalkan 4 kişi 24-28 temmuz"
      - "5 sleeps fethiye ağustos"
      - "24 temmuz - 28 temmuz kaş kalkan 6 kişi"
      - "28 ağustos 4 kişi"
      - "bank one 28 ağustos" (specific villa)

    Returns dict with: check_in, check_out, persons, locations, villa_name
    """
    text_lower = text.lower().strip()
    result = {
        "check_in": None,
        "check_out": None,
        "persons": 0,
        "locations": [],
        "villa_name": "",
    }

    this_year = date.today().year

    # ── Extract persons / sleeps ──────────────────────────────────────────
    # "4 kişi", "6 sleeps", "8 kişilik", "4 people"
    person_match = re.search(r"(\d+)\s*(?:kişi|sleeps?|kişilik|people?|persons?|pax|guest)", text_lower)
    if person_match:
        result["persons"] = int(person_match.group(1))
    else:
        # Bare number might be persons if small
        bare = re.findall(r"\b(\d+)\b", text_lower)
        for n in bare:
            num = int(n)
            if 1 <= num <= 20 and num > result["persons"]:
                # Don't confuse date parts with person counts
                if not re.search(rf"\b{num}\s*[-/]\s*\d+\b", text_lower) and not re.search(rf"\b\d+\s*[-/]\s*{num}\b", text_lower):
                    result["persons"] = num
                    break

    # ── Extract date ranges ──────────────────────────────────────────────
    # Pattern: "24-28 temmuz" or "24 temmuz - 28 temmuz" or "28 temmuz-20 ağustos"
    # Single date: "28 ağustos"
    dates_found = []

    # Multi-date with month each: "24 temmuz - 28 temmuz"
    range_match = re.search(
        r"(\d{1,2})\s*[-/]\s*(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|may|june|july|august|september|october|november|december)",
        text_lower
    )
    if range_match:
        d1, d2, month = int(range_match.group(1)), int(range_match.group(2)), range_match.group(3)
        m = _TR_MONTHS.get(month, 1)
        dates_found.append(date(this_year, m, d1))
        dates_found.append(date(this_year, m, d2))
    else:
        # Cross-month range: "28 temmuz-20 ağustos" or "28 temmuz - 20 ağustos"
        cross_match = re.search(
            r"(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|may|june|july|august|september|october|november|december)\s*[-/]\s*(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|may|june|july|august|september|october|november|december)",
            text_lower
        )
        if cross_match:
            d1, m1, d2, m2 = int(cross_match.group(1)), cross_match.group(2), int(cross_match.group(3)), cross_match.group(4)
            dates_found.append(date(this_year, _TR_MONTHS.get(m1, 1), d1))
            dates_found.append(date(this_year, _TR_MONTHS.get(m2, 1), d2))

    # Single dates: "24 temmuz", "ağustos"
    if not dates_found:
        single_dates = re.findall(
            r"(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|may|june|july|august|september|october|november|december)",
            text_lower
        )
        for d_str, month in single_dates:
            d = int(d_str)
            m = _TR_MONTHS.get(month, 1)
            dates_found.append(date(this_year, m, d))

        # Just a month name (e.g., "ağustos") → use full month
        if not dates_found:
            for month_name, m_num in _TR_MONTHS.items():
                if month_name in text_lower:
                    import calendar
                    last_day = calendar.monthrange(this_year, m_num)[1]
                    dates_found.append(date(this_year, m_num, 1))
                    dates_found.append(date(this_year, m_num, last_day))
                    break

    # Set check_in/check_out from found dates
    if len(dates_found) >= 2:
        dates_found.sort()
        result["check_in"] = dates_found[0]
        result["check_out"] = dates_found[-1]
    elif len(dates_found) == 1:
        # Single date → 3-night default stay
        result["check_in"] = dates_found[0]
        from datetime import timedelta
        result["check_out"] = dates_found[0] + timedelta(days=3)

    # ── Extract locations ────────────────────────────────────────────────
    for loc in _KNOWN_LOCATIONS:
        if loc in text_lower:
            # Map variants to canonical form
            canonical = {
                "kordere": "Kördere", "islamlar": "İslamlar", "uzumlu": "Üzümlü",
                "kas": "Kaş", "gokceoren": "Gökçeören", "kinik": "Kınık",
                "yesilkoy": "Yeşilköy", "cavdir": "Çavdır", "oludeniz": "Ölüdeniz",
                "subat": "Şubat",
            }
            mapped = canonical.get(loc, loc.title())
            if mapped not in result["locations"]:
                result["locations"].append(mapped)

    # ── Extract specific villa name ─────────────────────────────────────
    villa_names = [
        "au soleil", "bank one", "bank two", "beverley hills", "cornelia",
        "elia sun", "escala views", "good vibes one", "good vibes two",
        "hazal", "julia", "maiden asra", "maiden burcu", "mara sun",
        "marni", "max view", "morey", "olivella", "olivia",
        "ophelia bir", "ophelia iki", "ophelia trio", "ophelia dort",
        "overseas views", "resital", "samira one", "samira two",
        "samira three", "samira four", "tanyeli 1", "tanyeli 2",
        "tigra", "tzia", "villa sude", "villa sudem", "villa eslem",
    ]
    for vname in villa_names:
        if vname in text_lower:
            result["villa_name"] = vname.title()
            break

    return result


def format_villa_result(villa: dict) -> str:
    """Format a single villa result for Telegram."""
    status = "✅" if (villa["is_available"] and not villa["is_flagged"]) else "⚠️" if villa["is_available"] else "❌"
    line = f"{status} *{villa['name']}*"
    if villa.get("capacity"):
        line += f"  ({villa['capacity']}p)"
    if villa.get("locations"):
        line += f"  📍 {', '.join(villa['locations'])}"
    if villa.get("resital_url"):
        line += f"\n    🏠 {villa['resital_url']}"
    if villa.get("solmar_url"):
        line += f"\n    ☀️ {villa['solmar_url']}"

    if not villa["is_available"]:
        reason = villa.get("reason", "")
        # Truncate long reasons
        if len(reason) > 100:
            reason = reason[:97] + "..."
        line += f"\n    _{reason}_"

    return line
    """Start the Telegram bot (non-blocking)."""
    if not TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return

    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    except ImportError:
        logger.warning("python-telegram-bot not installed — bot disabled. pip install python-telegram-bot")
        return

    allowed = set(u.strip().lower() for u in ALLOWED_USERS.split(",") if u.strip())

    async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🏠 *Villa Matcher*\n\n"
            "Send me a Resort Report \\.xlsx file and I'll ingest it and rebuild occupancy data\\.\n\n"
            "Commands:\n"
            "/status — Show current occupancy stats\n"
            "/rebuild — Manually rebuild from all snapshots",
            parse_mode="MarkdownV2",
        )

    async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(REBUILD_URL.replace("/api/rebuild", "/api/stats"))
                if r.status_code == 200:
                    d = r.json()
                    occ = d["occupancy"]
                    msg = (
                        f"📊 *Occupancy Stats*\n\n"
                        f"Snapshots loaded: {d['snapshots_loaded']}\n"
                        f"Villas tracked: {d['villas_tracked']}\n"
                        f"• Confirmed: {occ['confirmed']}\n"
                        f"• Likely active: {occ['likely_active']}\n"
                        f"• Ambiguous: {occ['ambiguous']}\n"
                        f"• Deleted: {occ['deleted']}\n"
                        f"*Total: {occ['total']}*"
                    )
                else:
                    msg = "❌ Could not reach villa-matcher server"
        except Exception as e:
            msg = f"❌ Error: {e}"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def rebuild_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = await update.message.reply_text("🔄 Rebuilding occupancy data...")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(REBUILD_URL)
                if r.status_code == 200:
                    d = r.json()
                    await msg.edit_text(
                        f"✅ *Rebuild complete*\n\n"
                        f"Snapshots: {d['snapshots']}\n"
                        f"Records: {d['records']}",
                        parse_mode="Markdown",
                    )
                else:
                    await msg.edit_text(f"❌ Rebuild failed: {r.status_code}")
        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")

    async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        username = (user.username or "").lower()

        if allowed and username not in allowed:
            await update.message.reply_text("⛔ Access denied.")
            return

        doc = update.message.document
        if not doc or not doc.file_name:
            return

        fname = doc.file_name
        if not fname.lower().endswith(".xlsx"):
            await update.message.reply_text("⚠️ Please send a .xlsx file (Resort Report).")
            return

        msg = await update.message.reply_text(f"📥 Downloading {fname}...")

        try:
            # Download file
            file = await ctx.bot.get_file(doc.file_id)
            dest = os.path.join(SNAPSHOTS_DIR, fname)
            await file.download_to_drive(dest)
            await msg.edit_text(f"✅ Saved: {fname}\n🔄 Rebuilding...")

            # Trigger rebuild
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(REBUILD_URL)
                if r.status_code == 200:
                    d = r.json()
                    await msg.edit_text(
                        f"✅ *Ingested & rebuilt*\n\n"
                        f"📄 {fname}\n"
                        f"📊 {d['snapshots']} snapshots, {d['records']} records\n\n"
                        f"🌐 http://localhost:8080",
                        parse_mode="Markdown",
                    )
                else:
                    await msg.edit_text(f"⚠️ File saved but rebuild failed ({r.status_code}).\nTry /rebuild")
        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")

    # Build app
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("rebuild", rebuild_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    logger.info("Telegram bot started — send .xlsx files to trigger rebuild")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Keep running in background
    while True:
        await asyncio.sleep(3600)
