import os
import json
import logging
import pytz
import gspread
from datetime import time
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
BOT_TOKEN              = os.environ["BOT_TOKEN"]
GOOGLE_SHEET_ID        = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]
SHEET_TAB_NAME         = os.environ.get("SHEET_TAB_NAME", "Checklist")
COL_TASK               = os.environ.get("COL_TASK", "Task")
COL_CATEGORY           = os.environ.get("COL_CATEGORY", "Category")
COL_INSTRUCTIONS       = os.environ.get("COL_INSTRUCTIONS", "Instructions")
COL_EQUIPMENT          = os.environ.get("COL_EQUIPMENT", "Equipment")
COL_LOCATION           = os.environ.get("COL_LOCATION", "Location")
TEAM_NAMES             = [t.strip() for t in os.environ.get("TEAM_NAMES", "Team Alpha,Team Bravo,Team Charlie").split(",")]
ADMIN_USER_IDS         = [int(x.strip()) for x in os.environ.get("ADMIN_USER_IDS", "").split(",") if x.strip()]
RESET_HOUR             = int(os.environ.get("RESET_HOUR", "3"))
RESET_MINUTE           = int(os.environ.get("RESET_MINUTE", "0"))
TASKS_PER_PAGE         = 8
SGT                    = pytz.timezone("Asia/Singapore")

# ── In-memory store ───────────────────────────────────────────────────────────
_progress: dict[str, dict[int, bool]] = {team: {} for team in TEAM_NAMES}
_user_teams: dict[int, str] = {}
_tasks_cache: list[dict] = []

def set_user_team(user_id, team): _user_teams[user_id] = team
def get_user_team(user_id): return _user_teams.get(user_id)
def is_done(team, task_id): return _progress.get(team, {}).get(task_id, False)

def toggle_task(team, task_id):
    if team not in _progress: _progress[team] = {}
    current = _progress[team].get(task_id, False)
    _progress[team][task_id] = not current
    return not current

def get_team_progress(team, total):
    done = sum(1 for v in _progress.get(team, {}).values() if v)
    return {"done": done, "total": total, "pct": int(done / total * 100) if total else 0}

def get_all_progress(total):
    return {team: get_team_progress(team, total) for team in _progress}

def reset_all_progress():
    for team in _progress: _progress[team] = {}
    logger.info("All progress reset.")

def progress_bar(pct, width=10):
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

# ── Google Sheets ─────────────────────────────────────────────────────────────
def fetch_tasks(force=False):
    global _tasks_cache
    if _tasks_cache and not force:
        return _tasks_cache
    try:
        logger.info(f"[SHEETS] Parsing credentials JSON (length={len(GOOGLE_CREDENTIALS_JSON)})...")
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        logger.info(f"[SHEETS] client_email={creds_dict.get('client_email','MISSING')}")
        creds = Credentials.from_service_account_info(creds_dict, scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ])
        client = gspread.authorize(creds)
        logger.info(f"[SHEETS] Opening sheet ID={GOOGLE_SHEET_ID}, tab={SHEET_TAB_NAME}...")
        sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_TAB_NAME)
        records = sheet.get_all_records()
        logger.info(f"[SHEETS] Got {len(records)} rows.")
        tasks = []
        for i, row in enumerate(records):
            task = {
                "id": i,
                "task": str(row.get(COL_TASK, "")).strip(),
                "category": str(row.get(COL_CATEGORY, "")).strip(),
                "instructions": str(row.get(COL_INSTRUCTIONS, "")).strip(),
                "equipment": str(row.get(COL_EQUIPMENT, "")).strip(),
                "location": str(row.get(COL_LOCATION, "")).strip(),
            }
            if task["task"]:
                tasks.append(task)
        _tasks_cache = tasks
        logger.info(f"Fetched {len(tasks)} tasks.")
        return tasks
    except Exception as e:
        logger.error(f"Sheet fetch error: {e}")
        return _tasks_cache

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    current_team = get_user_team(user.id)
    keyboard = [[InlineKeyboardButton(f"👥 {team}", callback_data=f"team_{team}")] for team in TEAM_NAMES]
    if current_team:
        keyboard.append([InlineKeyboardButton("📋 View My Checklist", callback_data="view_checklist")])
    msg = (
        f"👋 Hi {user.first_name}! Welcome to the *FM Checklist Bot*.\n\n"
        + (f"✅ You are in *{current_team}*.\n\n" if current_team else "")
        + "Select your team to get started:"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def select_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    team = query.data.replace("team_", "", 1)
    set_user_team(update.effective_user.id, team)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Checklist", callback_data="view_checklist")],
        [InlineKeyboardButton("📊 My Team's Progress", callback_data="progress")],
    ])
    await query.edit_message_text(f"✅ You've joined *{team}*!\n\nWhat would you like to do?",
                                   parse_mode="Markdown", reply_markup=keyboard)


async def render_checklist(update, context, page=0):
    query = update.callback_query
    user = update.effective_user
    team = get_user_team(user.id)
    if not team:
        msg = "⚠️ You haven't selected a team yet. Use /start to pick your team."
        if query: await query.edit_message_text(msg)
        else: await update.message.reply_text(msg)
        return

    tasks = fetch_tasks()
    if not tasks:
        msg = "⚠️ No tasks found. Check your Google Sheet connection."
        if query: await query.edit_message_text(msg)
        else: await update.message.reply_text(msg)
        return

    total = len(tasks)
    start = page * TASKS_PER_PAGE
    end = min(start + TASKS_PER_PAGE, total)
    page_tasks = tasks[start:end]
    p = get_team_progress(team, total)

    header = (
        f"📋 *{team} — Checklist*\n"
        f"{progress_bar(p['pct'])} {p['done']}/{p['total']} done\n\n"
        f"Tap a task to view details & mark complete.\n"
    )

    keyboard = []
    for t in page_tasks:
        done = is_done(team, t["id"])
        icon = "✅" if done else "⬜"
        label = f"{icon} [{t['category']}] {t['task']}" if t["category"] else f"{icon} {t['task']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"task_{t['id']}")])

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < total: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("📊 Progress", callback_data="progress")])

    markup = InlineKeyboardMarkup(keyboard)
    if query: await query.edit_message_text(header, parse_mode="Markdown", reply_markup=markup)
    else: await update.message.reply_text(header, parse_mode="Markdown", reply_markup=markup)


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
    user = update.effective_user
    team = get_user_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id = int(query.data.replace("task_", ""))
    tasks = fetch_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    done = is_done(team, task_id)
    lines = [f"*{task['task']}*\n"]
    if task["category"]: lines.append(f"🏷️ *Category:* {task['category']}")
    lines.append(f"📌 *Status:* {'✅ Done' if done else '⬜ Not Done'}")
    if task["instructions"]: lines.append(f"\n📖 *Instructions:*\n{task['instructions']}")
    if task["equipment"]: lines.append(f"\n🔧 *Equipment needed:*\n{task['equipment']}")
    if task["location"]: lines.append(f"\n📍 *Where to get equipment:*\n{task['location']}")

    toggle_label = "✅ Mark as Done" if not done else "↩️ Mark as Not Done"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton("⬅️ Back to Checklist", callback_data="back_checklist")],
    ])
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def toggle_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    team = get_user_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id = int(query.data.replace("toggle_", ""))
    new_state = toggle_task(team, task_id)
    tasks = fetch_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    lines = [f"*{task['task']}*\n"]
    if task["category"]: lines.append(f"🏷️ *Category:* {task['category']}")
    lines.append(f"📌 *Status:* {'✅ Done' if new_state else '⬜ Not Done'}")
    if task["instructions"]: lines.append(f"\n📖 *Instructions:*\n{task['instructions']}")
    if task["equipment"]: lines.append(f"\n🔧 *Equipment needed:*\n{task['equipment']}")
    if task["location"]: lines.append(f"\n📍 *Where to get equipment:*\n{task['location']}")

    toggle_label = "✅ Mark as Done" if not new_state else "↩️ Mark as Not Done"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton("⬅️ Back to Checklist", callback_data="back_checklist")],
    ])
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    team = get_user_team(user.id)
    if query: await query.answer()

    tasks = fetch_tasks()
    total = len(tasks)

    if not team:
        msg = "⚠️ Please select a team first using /start."
    else:
        p = get_team_progress(team, total)
        remaining = p["total"] - p["done"]
        msg = (
            f"📊 *{team} — Today's Progress*\n\n"
            f"{progress_bar(p['pct'])} {p['pct']}%\n"
            f"✅ {p['done']} of {p['total']} tasks completed\n\n"
            + ("🎉 All tasks done! Great work today!" if remaining == 0 else f"🔲 {remaining} task(s) remaining.")
        )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Back to Checklist", callback_data="view_checklist")]])
    if query: await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else: await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return
    reset_all_progress()
    fetch_tasks(force=True)
    await update.message.reply_text("🔄 *Progress reset complete.* All teams cleared and tasks refreshed.", parse_mode="Markdown")


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return
    tasks = fetch_tasks()
    total = len(tasks)
    lines = ["📊 *All Teams — Progress Summary*\n"]
    for team, p in get_all_progress(total).items():
        bar = progress_bar(p["pct"])
        lines.append(f"*{team}*\n{bar} {p['pct']}%  ({p['done']}/{p['total']})\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Scheduler ─────────────────────────────────────────────────────────────────
async def daily_reset():
    logger.info("Daily reset running...")
    reset_all_progress()
    fetch_tasks(force=True)
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
