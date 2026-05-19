import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from config import BOT_TOKEN
from handlers.start import start_handler, select_team_handler
from handlers.checklist import (
    checklist_handler, task_detail_handler,
    toggle_task_handler, progress_handler
)
from handlers.admin import reset_handler, summary_handler
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("checklist", checklist_handler))
    app.add_handler(CommandHandler("progress", progress_handler))
    app.add_handler(CommandHandler("reset", reset_handler))
    app.add_handler(CommandHandler("summary", summary_handler))

    # Callback queries (inline button presses)
    app.add_handler(CallbackQueryHandler(select_team_handler,   pattern="^team_"))
    app.add_handler(CallbackQueryHandler(checklist_handler,     pattern="^view_checklist$"))
    app.add_handler(CallbackQueryHandler(task_detail_handler,   pattern="^task_\\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_task_handler,   pattern="^toggle_\\d+$"))
    app.add_handler(CallbackQueryHandler(progress_handler,      pattern="^progress$"))
    app.add_handler(CallbackQueryHandler(checklist_handler,     pattern="^back_checklist$"))

    # Setup daily reset scheduler
    setup_scheduler(app)

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
