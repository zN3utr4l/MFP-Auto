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
            await update.message.reply_text("Please /login first.")
            return
        password = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient(user.mfp_username, password)
        context.user_data["mfp_client"] = client

    msg = await update.message.reply_text("Retrying unsynced entries...")
    synced, failed = await retry_unsynced(db, client, user_id)

    await msg.edit_text(f"Retry complete: {synced} synced, {failed} failed.")
