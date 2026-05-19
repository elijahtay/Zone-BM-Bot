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
