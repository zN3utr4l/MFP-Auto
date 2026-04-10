from __future__ import annotations

import asyncio
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import import_range_keyboard
from db.database import encrypt_password, get_user, save_user
from db.models import User
from engine.pattern_analyzer import analyze_history
from mfp.client import MfpClient
from mfp.scraper import scrape_history


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user = await get_user(db, update.effective_user.id)

    if user and user.onboarding_done:
        await update.message.reply_text(
            "Welcome back! Use /today, /week, or /status."
        )
        return

    await update.message.reply_text(
        "Hi! To get started, I need your MyFitnessPal credentials.\n\n"
        "Send them in this format:\n"
        "`/login your_username your_password`\n\n"
        "The message will be deleted immediately for security.",
        parse_mode="Markdown",
    )


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]

    # Delete the message containing credentials immediately
    try:
        await update.message.delete()
    except Exception:
        pass

    args = context.args
    if not args or len(args) < 2:
        await update.effective_chat.send_message(
            "Usage: `/login username password`", parse_mode="Markdown"
        )
        return

    username = args[0]
    password = " ".join(args[1:])  # password may contain spaces

    # Test connection
    status_msg = await update.effective_chat.send_message(
        f"Connecting to MFP as {username}..."
    )

    try:
        client = MfpClient(username, password)
        # Test with today's date
        await client.get_day(date.today())
    except Exception as e:
        await status_msg.edit_text(f"Connection failed: {e}\nPlease check your credentials and try again.")
        return

    # Save user
    encrypted_pw = encrypt_password(password)
    user = User(
        telegram_user_id=update.effective_user.id,
        mfp_username=username,
        mfp_password_encrypted=encrypted_pw,
    )
    await save_user(db, user)

    # Store client in user_data for this session
    context.user_data["mfp_client"] = client

    await status_msg.edit_text(
        f"Connected as {username} on MFP!\n\n"
        "How much history should I import?",
        reply_markup=import_range_keyboard(),
    )


async def import_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    telegram_user_id = update.effective_user.id

    days = int(query.data.split(":")[1])
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Get or create MFP client
    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, telegram_user_id)
        if not user:
            await query.edit_message_text("Please /login first.")
            return
        from db.database import decrypt_password
        password = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient(user.mfp_username, password)
        context.user_data["mfp_client"] = client

    await query.edit_message_text(
        f"Importing {days} days of history... This may take a while.\n"
        f"(~{days} seconds at 1 request/second)"
    )

    async def on_progress(current_date: date, total: int) -> None:
        # Update message every 10 days to avoid rate limiting
        if (end_date - current_date).days % 10 == 0:
            try:
                await query.edit_message_text(
                    f"Importing... {current_date.isoformat()} ({total} entries so far)"
                )
            except Exception:
                pass

    total = await scrape_history(
        db, client, telegram_user_id, start_date, end_date, on_progress=on_progress
    )

    # Analyze patterns
    pattern_count = await analyze_history(db, telegram_user_id)

    # Mark onboarding done
    user = await get_user(db, telegram_user_id)
    user.onboarding_done = True
    await save_user(db, user)

    await query.edit_message_text(
        f"Bootstrap complete!\n"
        f"Imported: {total} entries\n"
        f"Patterns found: {pattern_count}\n\n"
        f"Try /today to see today's meals!"
    )
