from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.messages import format_status_line
from config import MEAL_SLOTS
from db.database import (
    decrypt_password,
    get_meal_entries,
    get_unsynced_entries,
    get_user,
)
from mfp.client import MfpClient
from mfp.sync import retry_unsynced


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()

    lines = ["\U0001F4CA Weekly Status\n"]

    for i in range(7):
        d = today + timedelta(days=i)
        logged = 0
        skipped = 0  # we can't know skipped from DB, just show logged vs pending
        for slot in MEAL_SLOTS:
            entries = await get_meal_entries(db, user_id, d.isoformat(), slot)
            if entries:
                logged += 1
        pending = len(MEAL_SLOTS) - logged
        lines.append(format_status_line(d.isoformat(), logged, pending, skipped))

    # Unsynced count
    unsynced = await get_unsynced_entries(db, user_id)
    if unsynced:
        lines.append(f"\n\u26A0 {len(unsynced)} entries not synced to MFP. Use /retry")

    await update.message.reply_text("\n".join(lines))


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    # Find the last entry inserted by this user
    async with db.execute(
        "SELECT * FROM meals_history WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        await update.message.reply_text("Nothing to undo.")
        return

    food_name = row["food_name"]
    entry_date = row["date"]
    slot = row["slot"]
    entry_id = row["id"]

    await db.execute("DELETE FROM meals_history WHERE id = ?", (entry_id,))
    await db.commit()

    await update.message.reply_text(
        f"\u21A9 Removed: {food_name} from {slot} on {entry_date}\n"
        "Note: if it was already synced to MFP, you'll need to remove it manually in the app."
    )


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, user_id)
        if not user:
            await update.message.reply_text("Please /start first.")
            return
        token_json = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient.from_auth_json(token_json)
        context.user_data["mfp_client"] = client

    msg = await update.message.reply_text("Retrying unsynced entries...")
    synced, failed = await retry_unsynced(db, client, user_id)

    await msg.edit_text(f"Retry complete: {synced} synced, {failed} failed.")


async def macros_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client
    from bot.messages import format_macro_summary

    client = await _ensure_client(update, context)
    if not client:
        return

    goals = context.user_data.get("macro_goals")
    if not goals:
        goals = await client.get_nutrient_goals()
        if goals:
            context.user_data["macro_goals"] = goals

    if not goals:
        await update.message.reply_text("Could not fetch your macro goals from MFP.")
        return

    totals = await client.get_day_totals(date.today())
    summary = format_macro_summary(totals, goals)
    await update.message.reply_text(summary or "No data for today yet.")


async def copy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client, _get_target_date, _send_macro_update, DAY_NAMES

    client = await _ensure_client(update, context)
    if not client:
        return

    if not context.args:
        await update.message.reply_text("Usage: `/copy yesterday` or `/copy monday`", parse_mode="Markdown")
        return

    arg = context.args[0].lower()
    today = date.today()

    if arg == "yesterday":
        source_date = today - timedelta(days=1)
    elif arg[:3] in DAY_NAMES:
        source_date = _get_target_date(arg)
        if source_date >= today:
            source_date -= timedelta(days=7)
    else:
        try:
            source_date = date.fromisoformat(arg)
        except ValueError:
            await update.message.reply_text(
                "Usage: `/copy yesterday`, `/copy monday`, or `/copy 2026-04-12`",
                parse_mode="Markdown",
            )
            return

    db = context.bot_data["db"]
    user_id = update.effective_user.id

    source_entries = await get_meal_entries(db, user_id, source_date.isoformat())
    if not source_entries:
        await update.message.reply_text(f"No meals found for {source_date.isoformat()}.")
        return

    msg = await update.message.reply_text(f"Copying from {source_date.isoformat()}...")

    from db.database import mark_entry_synced, save_meal_entry
    from db.models import MealEntry

    copied = 0
    skipped_slots = []
    slot_foods: dict[str, list[str]] = {}

    for entry in source_entries:
        existing = await get_meal_entries(db, user_id, today.isoformat(), entry.slot)
        if existing:
            if entry.slot not in skipped_slots:
                skipped_slots.append(entry.slot)
            continue

        new_entry = MealEntry(
            telegram_user_id=user_id,
            date=today.isoformat(),
            day_of_week=today.weekday(),
            slot=entry.slot,
            food_name=entry.food_name,
            quantity=entry.quantity,
            mfp_food_id=entry.mfp_food_id,
            source="bot_confirm",
            synced_to_mfp=False,
        )
        entry_id = await save_meal_entry(db, new_entry)

        if client and entry.mfp_food_id and entry.mfp_food_id not in ("", "None"):
            try:
                await client.add_entry(today.isoformat(), entry.slot, entry.food_name, entry.mfp_food_id)
                await mark_entry_synced(db, entry_id)
            except Exception:
                pass

        slot_foods.setdefault(entry.slot, []).append(entry.food_name)
        copied += 1

    lines = [f"Copied {copied} entries from {source_date.isoformat()}:"]
    for slot, foods in slot_foods.items():
        lines.append(f"  {slot}: {', '.join(foods)}")
    if skipped_slots:
        lines.append(f"  Skipped (already filled): {', '.join(skipped_slots)}")

    await msg.edit_text("\n".join(lines))
    await _send_macro_update(update, context, today)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client
    from bot.messages import format_history

    client = await _ensure_client(update, context)
    if not client:
        return

    goals = context.user_data.get("macro_goals")
    if not goals:
        goals = await client.get_nutrient_goals()
        if goals:
            context.user_data["macro_goals"] = goals

    msg = await update.message.reply_text("Loading 7-day history...")

    today = date.today()
    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        totals = await client.get_day_totals(d)
        days.append({"date": d.isoformat(), "totals": totals})

    text = format_history(days, goals or {})
    await msg.edit_text(text)
