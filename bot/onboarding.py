from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import import_range_keyboard
from db.database import encrypt_password, get_user, save_user
from db.models import User
from engine.pattern_analyzer import analyze_history
from mfp.client import MfpClient
from mfp.scraper import scrape_history

TOKEN_URL = "https://www.myfitnesspal.com/user/auth_token?refresh=true"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user = await get_user(db, update.effective_user.id)

    if user and user.onboarding_done:
        await update.message.reply_text(
            "Welcome back! Use /today, /week, or /status."
        )
        return

    await update.message.reply_text(
        "Hi! To connect your MyFitnessPal account:\n\n"
        "1. Login to myfitnesspal.com in your browser\n"
        f"2. Visit this URL:\n`{TOKEN_URL}`\n"
        "3. Copy ALL the text on the page\n"
        "4. Send it to me with:\n"
        "`/token paste_here`\n\n"
        "The message will be deleted immediately for security.",
        parse_mode="Markdown",
    )


async def token_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /token command — user provides MFP auth token JSON."""
    db = context.bot_data["db"]

    # Delete the message containing the token immediately
    try:
        await update.message.delete()
    except Exception:
        pass

    # Get the raw text after /token
    raw = update.message.text
    token_json = raw[len("/token"):].strip() if raw else ""

    if not token_json:
        await update.effective_chat.send_message(
            "Usage: `/token <paste the JSON from the auth page>`\n\n"
            f"Visit this URL while logged in:\n`{TOKEN_URL}`",
            parse_mode="Markdown",
        )
        return

    status_msg = await update.effective_chat.send_message("Verifying token...")

    try:
        client = MfpClient.from_auth_json(token_json)
        username = await client.validate()
    except Exception as e:
        await status_msg.edit_text(
            f"Token invalid: {e}\n\n"
            "Make sure you copied the ENTIRE text from the page."
        )
        return

    # Save user — store the token JSON encrypted
    encrypted_token = encrypt_password(token_json)
    user = User(
        telegram_user_id=update.effective_user.id,
        mfp_username=username,
        mfp_password_encrypted=encrypted_token,
    )
    await save_user(db, user)

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

    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, telegram_user_id)
        if not user:
            await query.edit_message_text("Please /start first.")
            return
        from db.database import decrypt_password
        token_json = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient.from_auth_json(token_json)
        context.user_data["mfp_client"] = client

    await query.edit_message_text(
        f"Importing {days} days of history... This may take a while.\n"
        f"(~{days} seconds at 1 request/second)"
    )

    async def on_progress(current_date: date, total: int) -> None:
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

    pattern_count = await analyze_history(db, telegram_user_id)

    user = await get_user(db, telegram_user_id)
    user.onboarding_done = True
    await save_user(db, user)

    await query.edit_message_text(
        f"Bootstrap complete!\n"
        f"Imported: {total} entries\n"
        f"Patterns found: {pattern_count}\n\n"
        f"Try /today to see today's meals!"
    )
