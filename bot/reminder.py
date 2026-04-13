from __future__ import annotations

import logging
from datetime import date, time

from telegram.ext import Application, ContextTypes

from config import MEAL_SLOTS, REMINDER_HOUR
from db.database import get_meal_entries

logger = logging.getLogger(__name__)


async def _count_empty_slots(db, telegram_user_id: int, target_date: date) -> int:
    """Count how many meal slots have no entries for the given date."""
    empty = 0
    for slot in MEAL_SLOTS:
        entries = await get_meal_entries(db, telegram_user_id, target_date.isoformat(), slot)
        if not entries:
            empty += 1
    return empty


async def _check_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: check all users for empty slots and send reminders."""
    db = context.application.bot_data.get("db")
    if not db:
        return

    today = date.today()

    async with db.execute(
        "SELECT telegram_user_id FROM users WHERE onboarding_done = 1"
    ) as cursor:
        users = [row["telegram_user_id"] async for row in cursor]

    for user_id in users:
        try:
            empty = await _count_empty_slots(db, user_id, today)
            if empty > 0:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"You have {empty} meal slots not logged today. Use /today to fill them.",
                )
        except Exception:
            logger.debug("Reminder failed for user %s", user_id, exc_info=True)


def schedule_reminders(application: Application) -> None:
    """Schedule the daily reminder job."""
    if application.job_queue is None:
        logger.warning("JobQueue not available — reminders disabled. Install python-telegram-bot[job-queue]")
        return
    application.job_queue.run_daily(
        _check_daily,
        time=time(hour=REMINDER_HOUR, minute=0),
        name="daily_reminder",
    )
