from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.daily import _ensure_client, start_day_flow
from bot.keyboards import stop_button
from config import MEAL_SLOTS, WEEK_TIMEOUT_MINUTES
from db.database import (
    get_active_week_progress,
    save_week_progress,
    update_week_progress,
)
from db.models import WeekProgress


def _is_timed_out(wp: WeekProgress) -> bool:
    """Check if a week progress has been inactive longer than WEEK_TIMEOUT_MINUTES."""
    try:
        updated = datetime.fromisoformat(wp.updated_at)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - updated).total_seconds() / 60
        return elapsed > WEEK_TIMEOUT_MINUTES
    except (ValueError, TypeError):
        return False


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()

    # Check for existing in-progress week
    existing = await get_active_week_progress(db, user_id)
    if existing:
        # Auto-stop if timed out
        if _is_timed_out(existing):
            await update_week_progress(db, existing.id, existing.current_day, "stopped")
            await update.message.reply_text(
                f"Previous week plan expired (inactive >{WEEK_TIMEOUT_MINUTES}min).\n"
                "Starting a new one..."
            )
            existing = None

    if existing:
        resume_date = date.fromisoformat(existing.current_day)
        context.user_data["week_mode"] = {
            "wp_id": existing.id,
            "start": date.fromisoformat(existing.week_start),
            "end": date.fromisoformat(existing.week_start) + timedelta(days=6),
            "current": resume_date,
        }
        await update.message.reply_text(
            f"Resuming week plan from {resume_date.isoformat()}.\n"
            "I'll skip days that are already filled in MFP.",
            reply_markup=stop_button(),
        )
        await _start_next_day(update, context)
        return

    # Start new week
    end_date = today + timedelta(days=6)
    wp = WeekProgress(
        telegram_user_id=user_id,
        week_start=today.isoformat(),
        current_day=today.isoformat(),
    )
    wp_id = await save_week_progress(db, wp)

    context.user_data["week_mode"] = {
        "wp_id": wp_id,
        "start": today,
        "end": end_date,
        "current": today,
    }

    await update.message.reply_text(
        f"\U0001F4C5 Week plan: {today.isoformat()} to {end_date.isoformat()}\n"
        "MFP is the source of truth, so filled days will be skipped automatically.",
        reply_markup=stop_button(),
    )
    await _start_next_day(update, context)


async def _start_next_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Find the next day that needs filling and start its flow."""
    week = context.user_data.get("week_mode", {})
    client = context.user_data.get("mfp_client")

    current = week.get("current", date.today())
    end = week.get("end", date.today())

    while current <= end:
        # MFP is the source of truth for whether a day is already complete.
        if client:
            from bot.daily import _fetch_mfp_filled_slots
            filled_slots = await _fetch_mfp_filled_slots(client, current)
            all_filled = len(filled_slots) == len(MEAL_SLOTS)
        else:
            all_filled = False

        if not all_filled:
            week["current"] = current
            day_index = (current - week["start"]).days + 1
            total_days = (week["end"] - week["start"]).days + 1
            await start_day_flow(update, context, current, day_index, total_days)
            return

        current += timedelta(days=1)

    # All days done
    await _complete_week(update, context)


async def advance_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called after a day flow completes to move to the next day."""
    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if not week:
        return

    current = week["current"] + timedelta(days=1)
    week["current"] = current

    await update_week_progress(db, week["wp_id"], current.isoformat(), "in_progress")

    if current > week["end"]:
        await _complete_week(update, context)
        return

    await update.effective_chat.send_message("---", reply_markup=stop_button())
    await _start_next_day(update, context)


async def week_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if not week:
        await query.edit_message_text("No active week plan.")
        return

    await update_week_progress(db, week["wp_id"], week["current"].isoformat(), "stopped")
    context.user_data.pop("week_mode", None)
    context.user_data.pop("current_day", None)

    await query.edit_message_text(
        f"\u23F9 Week plan paused at {week['current'].isoformat()}.\n"
        "Use /week to resume from there."
    )


async def _complete_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if week:
        await update_week_progress(db, week["wp_id"], week["end"].isoformat(), "completed")
    context.user_data.pop("week_mode", None)
    context.user_data.pop("current_day", None)

    await update.effective_chat.send_message(
        "\u2705 Week plan complete! All days are already filled or have been processed."
    )
