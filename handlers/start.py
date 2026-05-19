# handlers package

from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_USER_IDS
from store import reset_all_progress, get_all_progress, get_all_teams
from sheets import fetch_tasks, refresh_tasks


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: manually reset all team progress and refresh the task list."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return

    reset_all_progress()
    refresh_tasks()
    await update.message.reply_text(
        "🔄 *Progress reset complete.*\n\n"
        "All team checklists have been cleared and tasks refreshed from Google Sheets.",
        parse_mode="Markdown"
    )


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: show a progress summary across all teams."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("🚫 You don't have permission to use this command.")
        return

    tasks = fetch_tasks()
    total = len(tasks)
    all_progress = get_all_progress(total)

    lines = ["📊 *All Teams — Progress Summary*\n"]
    for team, p in all_progress.items():
        bar = "█" * int(10 * p["pct"] / 100) + "░" * (10 - int(10 * p["pct"] / 100))
        lines.append(f"*{team}*\n{bar} {p['pct']}%  ({p['done']}/{p['total']})\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sheets import fetch_tasks
from store import get_user_team, is_done, toggle_task, get_team_progress

TASKS_PER_PAGE = 8


def _require_team(user_id: int) -> str | None:
    return get_user_team(user_id)


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


async def checklist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the paginated checklist for the user's team."""
    query = update.callback_query
    user = update.effective_user

    team = _require_team(user.id)
    if not team:
        msg = "⚠️ You haven't selected a team yet. Use /start to pick your team."
        if query:
            await query.answer()
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    if query:
        await query.answer()

    tasks = fetch_tasks()
    if not tasks:
        msg = "⚠️ No tasks found. The checklist might be empty or there's a connection issue."
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    # Determine page
    page = int((context.user_data or {}).get("page", 0))
    if query and query.data == "view_checklist":
        page = 0
    if context.user_data:
        context.user_data["page"] = page

    total = len(tasks)
    start = page * TASKS_PER_PAGE
    end   = min(start + TASKS_PER_PAGE, total)
    page_tasks = tasks[start:end]

    # Group by category for display
    progress = get_team_progress(team, total)
    header = (
        f"📋 *{team} — Checklist*\n"
        f"{_progress_bar(progress['pct'])} {progress['done']}/{progress['total']} done\n\n"
        f"Tap a task to view details & mark complete.\n"
    )

    keyboard = []
    for t in page_tasks:
        done  = is_done(team, t["id"])
        icon  = "✅" if done else "⬜"
        label = f"{icon} {t['task']}"
        if t["category"]:
            label = f"{icon} [{t['category']}] {t['task']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"task_{t['id']}")])

    # Pagination controls
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("📊 Progress", callback_data="progress")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(header, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(header, parse_mode="Markdown", reply_markup=reply_markup)


async def task_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full task details with toggle button."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    team = _require_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id = int(query.data.replace("task_", ""))
    tasks   = fetch_tasks()
    task    = next((t for t in tasks if t["id"] == task_id), None)

    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    done = is_done(team, task_id)
    status_icon = "✅ Done" if done else "⬜ Not Done"

    lines = [f"*{task['task']}*\n"]
    if task["category"]:
        lines.append(f"🏷️ *Category:* {task['category']}")
    lines.append(f"📌 *Status:* {status_icon}")
    if task["instructions"]:
        lines.append(f"\n📖 *Instructions:*\n{task['instructions']}")
    if task["equipment"]:
        lines.append(f"\n🔧 *Equipment needed:*\n{task['equipment']}")
    if task["location"]:
        lines.append(f"\n📍 *Where to get equipment:*\n{task['location']}")

    toggle_label = "✅ Mark as Done" if not done else "↩️ Mark as Not Done"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton("⬅️ Back to Checklist", callback_data="back_checklist")],
    ])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def toggle_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle a task's done state and refresh the detail view."""
    query = update.callback_query
    await query.answer()

    user    = update.effective_user
    team    = _require_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    task_id  = int(query.data.replace("toggle_", ""))
    new_state = toggle_task(team, task_id)

    tasks = fetch_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    status_icon = "✅ Done" if new_state else "⬜ Not Done"
    lines = [f"*{task['task']}*\n"]
    if task["category"]:
        lines.append(f"🏷️ *Category:* {task['category']}")
    lines.append(f"📌 *Status:* {status_icon}")
    if task["instructions"]:
        lines.append(f"\n📖 *Instructions:*\n{task['instructions']}")
    if task["equipment"]:
        lines.append(f"\n🔧 *Equipment needed:*\n{task['equipment']}")
    if task["location"]:
        lines.append(f"\n📍 *Where to get equipment:*\n{task['location']}")

    toggle_label = "✅ Mark as Done" if not new_state else "↩️ Mark as Not Done"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"toggle_{task_id}")],
        [InlineKeyboardButton("⬅️ Back to Checklist", callback_data="back_checklist")],
    ])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show team progress summary."""
    query  = update.callback_query
    user   = update.effective_user
    team   = _require_team(user.id)

    if query:
        await query.answer()

    tasks = fetch_tasks()
    total = len(tasks)

    if not team:
        msg = "⚠️ Please select a team first using /start."
    else:
        p = get_team_progress(team, total)
        bar = _progress_bar(p["pct"])
        msg = (
            f"📊 *{team} — Today's Progress*\n\n"
            f"{bar} {p['pct']}%\n"
            f"✅ {p['done']} of {p['total']} tasks completed\n\n"
        )
        remaining = p["total"] - p["done"]
        if remaining == 0:
            msg += "🎉 All tasks done! Great work today!"
        else:
            msg += f"🔲 {remaining} task(s) remaining."

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Back to Checklist", callback_data="view_checklist")]
    ])

    if query:
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)


async def page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination — jump to a specific page of the checklist."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.replace("page_", ""))
    if context.user_data is not None:
        context.user_data["page"] = page

    user = update.effective_user
    team = _require_team(user.id)
    if not team:
        await query.edit_message_text("⚠️ Please select a team first using /start.")
        return

    tasks = fetch_tasks()
    total = len(tasks)
    start = page * TASKS_PER_PAGE
    end   = min(start + TASKS_PER_PAGE, total)
    page_tasks = tasks[start:end]

    progress = get_team_progress(team, total)
    header = (
        f"📋 *{team} — Checklist*\n"
        f"{_progress_bar(progress['pct'])} {progress['done']}/{progress['total']} done\n\n"
        f"Tap a task to view details & mark complete.\n"
    )

    keyboard = []
    for t in page_tasks:
        done  = is_done(team, t["id"])
        icon  = "✅" if done else "⬜"
        label = f"{icon} [{t['category']}] {t['task']}" if t["category"] else f"{icon} {t['task']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"task_{t['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("📊 Progress", callback_data="progress")])

    await query.edit_message_text(
        header, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from store import set_user_team, get_user_team, get_all_teams


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message + team selection."""
    user = update.effective_user
    current_team = get_user_team(user.id)

    teams = get_all_teams()
    keyboard = [
        [InlineKeyboardButton(f"👥 {team}", callback_data=f"team_{team}")]
        for team in teams
    ]

    if current_team:
        keyboard.append([
            InlineKeyboardButton("📋 View My Checklist", callback_data="view_checklist")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"👋 Hi {user.first_name}! Welcome to the *FM Checklist Bot*.\n\n"
        f"{'✅ You are currently in *' + current_team + '*.' + chr(10) + chr(10) if current_team else ''}"
        "Please select your team to get started:"
    )

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)


async def select_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle team selection button press."""
    query = update.callback_query
    await query.answer()

    team_name = query.data.replace("team_", "", 1)
    user = update.effective_user
    set_user_team(user.id, team_name)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Checklist", callback_data="view_checklist")],
        [InlineKeyboardButton("📊 My Team's Progress", callback_data="progress")],
    ])

    await query.edit_message_text(
        f"✅ You've joined *{team_name}*!\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
