"""
scheduler.py — schedules a daily reset of all team progress.

Reset time is configurable via RESET_HOUR / RESET_MINUTE in config.py
(default: 3:00 AM Singapore time, UTC+8 → 19:00 UTC previous day).
"""

import logging
import pytz
from datetime import time
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from store import reset_all_progress
from sheets import refresh_tasks
from config import RESET_HOUR, RESET_MINUTE

logger = logging.getLogger(__name__)

SGT = pytz.timezone("Asia/Singapore")


async def _daily_reset():
    logger.info("Running scheduled daily reset...")
    reset_all_progress()
    refresh_tasks()
    logger.info("Daily reset complete.")


def setup_scheduler(app: Application):
    scheduler = AsyncIOScheduler(timezone=SGT)
    scheduler.add_job(
        _daily_reset,
        trigger=CronTrigger(hour=RESET_HOUR, minute=RESET_MINUTE, timezone=SGT),
        id="daily_reset",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — daily reset at {RESET_HOUR:02d}:{RESET_MINUTE:02d} SGT")
