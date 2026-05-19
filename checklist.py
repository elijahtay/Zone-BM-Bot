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
