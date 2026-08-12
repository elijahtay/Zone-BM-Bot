import os
import json
import logging
from datetime import datetime
import pytz
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN               = os.environ["BOT_TOKEN"]
GOOGLE_SHEET_ID         = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]
SHEET_TAB_NAME          = os.environ.get("SHEET_TAB_NAME", "Tasks")
WEEKEND_SHEET_TAB_NAME  = os.environ.get("WEEKEND_SHEET_TAB_NAME", "Weekend")
COL_TASK                = os.environ.get("COL_TASK", "Task")
COL_CATEGORY            = os.environ.get("COL_CATEGORY", "Category")
COL_INSTRUCTIONS        = os.environ.get("COL_INSTRUCTIONS", "Task Description")
COL_EQUIPMENT           = os.environ.get("COL_EQUIPMENT", "Equipment")
COL_LOCATION            = os.environ.get("COL_LOCATION", "Area")
ADMIN_USER_IDS          = [int(x.strip()) for x in os.environ.get("ADMIN_USER_IDS", "").split(",") if x.strip()]
RESET_HOUR              = int(os.environ.get("RESET_HOUR", "3"))
RESET_MINUTE            = int(os.environ.get("RESET_MINUTE", "0"))
TASKS_PER_PAGE          = 8
SGT                     = pytz.timezone("Asia/Singapore")
WEEKEND_ID_OFFSET       = 100_000  # keeps weekend-tab task IDs from colliding with daily-tab task IDs

# ── Team → Areas mapping ──────────────────────────────────────────────────────
# Location values must match exactly what's in your Google Sheet's Area column (COL_LOCATION)
TEAM_AREAS = {
    "Atrium":         ["Atrium"],
    "Keyboard Male Toilets":   ["Keyboard Male Toilet"],
    "Drums Male Toilet":        [ "Drums Male Toilet"],
    "Keyboard Female Toilet": ["Keyboard Female Toilet"],
    "Drums Female Toilet":        ["Drums Female Toilet"],
    "Audi":           ["Auditorium"],
    "Lift Lobby":     ["Lift Lobby & Concept Walkway"],
}

TEAM_NAMES = list(TEAM_AREAS.keys())

# ── In-memory store ───────────────────────────────────────────────────────────
_progress: dict[str, dict[int, bool]] = {team: {} for team in TEAM_NAMES}
_user_teams: dict[int, str] = {}
_tasks_cache: list[dict] = []
_weekend_tasks_cache: list[dict] = []

def set_user_team(user_id: int, team: str): _user_teams[user_id] = team
def get_user_team(user_id: int): return _user_teams.get(user_id)

def is_done(team: str, task_id: int) -> bool:
    return _progress.get(team, {}).get(task_id, False)

def toggle_task(team: str, task_id: int) -> bool:
    if team not in _progress: _progress[team] = {}
    current = _progress[team].get(task_id, False)
    _progress[team][task_id] = not current
    return not current

def is_weekend() -> bool:
    """True on Saturday/Sunday, Singapore time."""
    return datetime.now(SGT).weekday() >= 5  # Mon=0 ... Sat=5, Sun=6

def get_all_tasks_for_today() -> list[dict]:
    """Daily tasks, plus weekend-tab tasks on Sat/Sun."""
    tasks = list(fetch_tasks())
    if is_weekend():
        tasks += fetch_weekend_tasks()
    return tasks

def find_task_by_id(task_id: int) -> dict | None:
    return next((t for t in get_all_tasks_for_today() if t["id"] == task_id), None)

def get_team_tasks(team: str) -> list[dict]:
    """Return only today's tasks whose Location matches the team's assigned areas."""
    areas = TEAM_AREAS.get(team, [])
    return [t for t in get_all_tasks_for_today() if t["location"] in areas]

def get_team_progress(team: str) -> dict:
    tasks = get_team_tasks(team)
    total = len(tasks)
    done  = sum(1 for t in tasks if is_done(team, t["id"]))
    return {"done": done, "total": total, "pct": int(done / total * 100) if total else 0}

def get_all_progress() -> dict:
    return {team: get_team_progress(team) for team in TEAM_NAMES}

def reset_all_progress():
    for team in _progress: _progress[team] = {}
    logger.info("All progress reset.")

def progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

# ── Google Sheets ─────────────────────────────────────────────────────────────
def _fetch_tasks_from_tab(tab_name: str, id_offset: int = 0) -> list[dict]:
    """Read one worksheet tab and return it as a list of task dicts."""
    logger.info(f"[SHEETS] Parsing credentials JSON (length={len(GOOGLE_CREDENTIALS_JSON)})...")
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    logger.info(f"[SHEETS] client_email={creds_dict.get('client_email', 'MISSING')}")
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    client  = gspread.authorize(creds)
    logger.info(f"[SHEETS] Opening sheet ID={GOOGLE_SHEET_ID}, tab={tab_name}...")
    sheet   = client.open_by_key(GOOGLE_SHEET_ID).worksheet(tab_name)
    records = sheet.get_all_records()
    logger.info(f"[SHEETS] Got {len(records)} rows from '{tab_name}'.")
    tasks = []
    for i, row in enumerate(records):
        task = {
            "id":           id_offset + i,
            "task":         str(row.get(COL_TASK, "")).strip(),
            "category":     str(row.get(COL_CATEGORY, "")).strip(),
            "instructions": str(row.get(COL_INSTRUCTIONS, "")).strip(),
            "equipment":    str(row.get(COL_EQUIPMENT, "")).strip(),
            "location":     str(row.get(COL_LOCATION, "")).strip(),
        }
        if task["task"]:
            tasks.append(task)
    return tasks


def fetch_tasks(force: bool = False) -> list[dict]:
    global _tasks_cache
    if _tasks_cache and not force:
        return _tasks_cache
    try:
        tasks = _fetch_tasks_from_tab(SHEET_TAB_NAME)
        _tasks_cache = tasks
        logger.info(f"[SHEETS] Cached {len(tasks)} tasks.")
        return tasks
    except Exception as e:
        logger.error(f"Sheet fetch error: {e}")
        return _tasks_cache


def fetch_weekend_tasks(force: bool = False) -> list[dict]:
    """Same as fetch_tasks(), but reads the weekend-only tab (e.g. 'Weekend')."""
    global _weekend_tasks_cache
    if _weekend_tasks_cache and not force:
        return _weekend_tasks_cache
    try:
        tasks = _fetch_tasks_from_tab(WEEKEND_SHEET_TAB_NAME, id_offset=WEEKEND_ID_OFFSET)
        _weekend_tasks_cache = tasks
        logger.info(f"[SHEETS] Cached {len(tasks)} weekend tasks.")
        return tasks
    except Exception as e:
        logger.error(f"Weekend sheet fetch error: {e}")
        return _weekend_tasks_cache

# ── Keyboards ─────────────────────────────────────────────────────────────────
def team_selection_keyboard(current_team: str = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"👥 {team}", callback_data=f"team_{team}")] for team in TEAM_NAMES]
    if current_team:
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Checklist",      callback_data="view_checklist")],
        [InlineKeyboardButton("📊 My Team's Progress",  callback_data="progress")],
        [InlineKeyboardButton("🔄 Change Team",         callback_data="change_team")],
    ])

def checklist_keyboard(page_tasks, team, page, total_tasks, end) -> InlineKeyboardMarkup:
    rows = []
    for t in page_tasks:
        icon  = "✅" if is_done(team, t["id"]) else "⬜"
        rows.append([InlineKeyboardButton(f"{icon} {t['task']}", callback_data=f"task_{t['id']}")])
    nav = []
    if page > 0:          nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < total_tasks: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav: rows.append(nav)
    rows.append([
        InlineKeyboardButton("📊 Progress",  callback_data="progress"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)

def task_keyboard(task_id: int, done: bool) -> InlineKeyboardMarkup:
    toggle_label = "✅ Mark as Done" if not done else "↩️ Mark as Not Done"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label,               callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton("⬅️ Back to Checklist",     callback_data="back_checklist")],
        [InlineKeyboardButton("🏠 Main Menu",              callback_data="main_menu")],
    ])

def progress_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Back to Checklist", callback_data="view_checklist")],
        [InlineKeyboardButton("🏠 Main Menu",          callback_data="main_menu")],
    ])

# ── Helpers ───────────────────────────────────────────────────────────────────
def task_detail_text(task: dict, team: str) -> str:
    done  = is_done(team, task["id"])
    lines = [f"*{task['task']}*\n"]
    if task["category"]:     lines.append(f"🏷️ *Category:* {task['category']}")
    if task["location"]:     lines.append(f"📍 *Area:* {task['location']}")
    lines.append(f"📌 *Status:* {'✅ Done' if done else '⬜ Not Done'}")
    if task["instructions"]: lines.append(f"\n📖 *Instructions:*\n{task['instructions']}")
    if task["equipment"]:    lines.append(f"\n🔧 *Equipment needed:*\n{task['equipment']}")
    return "\n".join(lines)

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user         = update.effective_user
    current_team = get_user_team(user.id)
    msg = (
        f"👋 Hi {user.first_name}! Welcome to the *Zone BM Checklist Bot*.\n\n"
        + (f"✅ You are currently in *{current_team}*.\n\n" if current_team else "")
        + "Select your team to get started:"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=team_selection_keyboard(current_team))
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=team_selection_keyboard(current_team))


async def select_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    team  = query.data.replace("team_", "", 1)
    set_user_team(update.effective_user.id, team)

    areas      = TEAM_AREAS.get(team, [])
    areas_text = "\n".join(f"  • {a}" for a in areas)

    # Special notice for Female Toilets team
    special_notice = ""
    if team in ("Keyboard Female Toilet", "Drums Female Toilet"):
        special_notice = (
            "\n\n⚠️ *Important Reminder:*\n"
            "Please note _not_ to wet wash the nursing room areas in the female toilets 🙂"
        )

    await query.edit_message_text(
        f"✅ You've joined *{team}*!\n\n"
        f"📍 *Your assigned areas:*\n{areas_text}"
        f"{special_notice}\n\n"
        f"What would you like to do?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    team  = get_user_team(user.id)

    if not team:
        await query.edit_message_text(
            "⚠️ Please select a team first.",
            reply_markup=team_selection_keyboard()
        )
        return

    areas      = TEAM_AREAS.get(team, [])
    areas_text = "\n".join(f"  • {a}" for a in areas)
    p          = get_team_progress(team)

    await query.edit_message_text(
        f"🏠 *Main Menu*\n\n"
        f"👥 Team: *{team}*\n"
        f"📍 Areas:\n{areas_text}\n\n"
        f"📊 Progress today: {progress_bar(p['pct'])} {p['done']}/{p['total']}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def change_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query        = update.callback_query
    await query.answer()
    current_team = get_user_team(update.effective_user.id)
    await query.edit_message_text(
        "🔄 *Change Team*\n\nSelect your new team:",
        parse_mode="Markdown",
        reply_markup=team_selection_keyboard(current_team)
    )


async def render_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    query = update.callback_query
    user  = update.effective_user
    team  = get_user_team(user.id)

    if not team:
        msg = "⚠️ You haven't selected a team yet. Use /start to pick your team."
        if query: await query.edit_message_text(msg)
        else:     await update.message.reply_text(msg)
        return

    tasks = get_team_tasks(team)
    if not tasks:
        msg = (
            f"⚠️ No tasks found for *{team}*.\n\n"
            f"Assigned areas: {', '.join(TEAM_AREAS.get(team, []))}\n\n"
            f"_Check that the {COL_LOCATION} column in your sheet matches exactly._"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        if query: await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=markup)
        else:     await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        return

    total      = len(tasks)
    start      = page * TASKS_PER_PAGE
    end        = min(start + TASKS_PER_PAGE, total)
    page_tasks = tasks[start:end]
    p          = get_team_progress(team)
    areas      = ", ".join(TEAM_AREAS.get(team, []))

    weekend_note = "\n🎉 _Weekend tasks included today_" if is_weekend() else ""
    header = (
        f"📋 *{team} Checklist*\n"
        f"📍 _{areas}_"
        f"{weekend_note}\n"
        f"{progress_bar(p['pct'])} {p['done']}/{p['total']} done\n\n"
        f"Tap a task to view details & mark complete."
    )

    markup = checklist_keyboard(page_tasks, team, page, total, end)
    if query: await query.edit_message_text(header, parse_mode="Markdown", reply_markup=markup)
    else:     await update.message.reply_text(header, parse_mode="Markdown", reply_markup=markup)


async def checklist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    page = context.user_data.get("page", 0) if context.user_data else 0
    if update.callback_query and update.callback_query.data in ("view_checklist", "back_checklist"):
        page = 0
    await render_checklist(update, context, page)


async def page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.replace("page_", ""))
    if context.user_data is not None: context.user_data["page"] = page
    await render_checklist(update, context, page)


async def task_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    team  = get_user_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id = int(query.data.replace("task_", ""))
    task    = find_task_by_id(task_id)
    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    await query.edit_message_text(
        task_detail_text(task, team),
        parse_mode="Markdown",
        reply_markup=task_keyboard(task_id, is_done(team, task_id))
    )


async def toggle_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    team  = get_user_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id   = int(query.data.replace("toggle_", ""))
    new_state = toggle_task(team, task_id)
    task      = find_task_by_id(task_id)
    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    await query.edit_message_text(
        task_detail_text(task, team),
        parse_mode="Markdown",
        reply_markup=task_keyboard(task_id, new_state)
    )


async def progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = update.effective_user
    team  = get_user_team(user.id)
    if query: await query.answer()

    if not team:
        msg = "⚠️ Please select a team first using /start."
    else:
        p         = get_team_progress(team)
        remaining = p["total"] - p["done"]
        undone    = [t["task"] for t in get_team_tasks(team) if not is_done(team, t["id"])]
        msg = (
            f"📊 *{team} — Today's Progress*\n\n"
            f"{progress_bar(p['pct'])} {p['pct']}%\n"
            f"✅ {p['done']} of {p['total']} tasks completed\n\n"
        )
        if remaining == 0:
            msg += "🎉 All tasks done! Great work today!"
        else:
            msg += f"🔲 *{remaining} remaining:*\n"
            msg += "\n".join(f"  • {t}" for t in undone[:10])
            if len(undone) > 10:
                msg += f"\n  _...and {len(undone)-10} more_"

    if query: await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=progress_keyboard())
    else:     await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=progress_keyboard())


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return
    reset_all_progress()
    fetch_tasks(force=True)
    fetch_weekend_tasks(force=True)
    await update.message.reply_text(
        "🔄 *Progress reset complete.*\nAll teams cleared and tasks refreshed from Google Sheets.",
        parse_mode="Markdown"
    )


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return
    lines = ["📊 *All Teams — Progress Summary*\n"]
    for team, p in get_all_progress().items():
        lines.append(f"*{team}*\n{progress_bar(p['pct'])} {p['pct']}%  ({p['done']}/{p['total']})\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Scheduler ─────────────────────────────────────────────────────────────────
async def daily_reset():
    logger.info("Daily reset running...")
    reset_all_progress()
    fetch_tasks(force=True)
    fetch_weekend_tasks(force=True)
    logger.info("Daily reset complete.")

def setup_scheduler(app):
    scheduler = AsyncIOScheduler(timezone=SGT)
    scheduler.add_job(daily_reset, CronTrigger(hour=RESET_HOUR, minute=RESET_MINUTE, timezone=SGT))
    scheduler.start()
    logger.info(f"Scheduler set for {RESET_HOUR:02d}:{RESET_MINUTE:02d} SGT daily.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     start_handler))
    app.add_handler(CommandHandler("checklist", checklist_handler))
    app.add_handler(CommandHandler("progress",  progress_handler))
    app.add_handler(CommandHandler("reset",     reset_handler))
    app.add_handler(CommandHandler("summary",   summary_handler))

    app.add_handler(CallbackQueryHandler(select_team_handler,  pattern="^team_"))
    app.add_handler(CallbackQueryHandler(main_menu_handler,    pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(change_team_handler,  pattern="^change_team$"))
    app.add_handler(CallbackQueryHandler(checklist_handler,    pattern="^view_checklist$"))
    app.add_handler(CallbackQueryHandler(checklist_handler,    pattern="^back_checklist$"))
    app.add_handler(CallbackQueryHandler(task_detail_handler,  pattern="^task_\\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_task_handler,  pattern="^toggle_\\d+$"))
    app.add_handler(CallbackQueryHandler(progress_handler,     pattern="^progress$"))
    app.add_handler(CallbackQueryHandler(page_handler,         pattern="^page_\\d+$"))

    setup_scheduler(app)
    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
