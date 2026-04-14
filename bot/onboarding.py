from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import import_range_keyboard
from db.database import decrypt_password, encrypt_password, get_user, save_user
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
            "Welcome back!\n\n"
            "/today — log today's meals\n"
            "/tomorrow — plan tomorrow\n"
            "/week — plan the whole week\n"
            "/macros — check remaining macros\n"
            "/suggest — what to eat next\n"
            "/copy yesterday — repeat a day\n"
            "/history — 7-day overview\n"
            "/setup — reconfigure your foods\n"
            "/import — import MFP history\n"
            "/status — slots overview",
        )
        return

    await update.message.reply_text(
        "Welcome to MFP Auto Bot!\n"
        "I'll help you log meals on MyFitnessPal faster.\n\n"
        "Let's connect your account. Here's how:\n\n"
        "*Step 1:* Open your browser and log into myfitnesspal.com\n\n"
        "*Step 2:* Once logged in, open this link:\n"
        f"`{TOKEN_URL}`\n\n"
        "*Step 3:* You'll see a page with JSON text "
        '(starts with `{"access_token":...}`). '
        "Select ALL the text and copy it.\n\n"
        "*Step 4:* Come back here and send:\n"
        "`/token <paste the text here>`\n\n"
        "Your token will be deleted from chat immediately for security.",
        parse_mode="Markdown",
    )


async def token_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /token command — user provides MFP auth token JSON."""
    db = context.bot_data["db"]

    try:
        await update.message.delete()
    except Exception:
        pass

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

    encrypted_token = encrypt_password(token_json)
    user = User(
        telegram_user_id=update.effective_user.id,
        mfp_username=username,
        mfp_password_encrypted=encrypted_token,
        onboarding_done=True,
    )
    await save_user(db, user)

    context.user_data["mfp_client"] = client

    await status_msg.edit_text(
        f"Connected as *{username}* on MFP!\n\n"
        "*What's next?*\n\n"
        "*Option A — Import history (recommended):*\n"
        "Send /import to import your MFP diary. "
        "I'll learn your exact foods and portions. "
        "Predictions work from day 1.\n\n"
        "*Option B — Quick manual setup:*\n"
        "Send /setup to search and register your typical foods.\n\n"
        "*Option C — Jump right in:*\n"
        "Send /today and I'll learn as you go.",
        parse_mode="Markdown",
    )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show import range selection."""
    from bot.daily import _ensure_client

    client = await _ensure_client(update, context)
    if not client:
        return

    await update.message.reply_text(
        "How much history should I import?\n"
        "(Each day takes ~1 second)",
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
        token_json = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient.from_auth_json(token_json)
        context.user_data["mfp_client"] = client

    await query.edit_message_text(
        f"Importing {days} days of history...\n"
        f"(~{days} seconds at 1 request/second)\n\n"
        "This runs in the background. I'll message you when it's done."
    )

    total = 0
    errors = 0

    async def on_progress(current_date: date, count: int) -> None:
        nonlocal total
        total = count
        elapsed = (end_date - current_date).days
        if elapsed % 30 == 0 and elapsed > 0:
            try:
                await query.edit_message_text(
                    f"Importing... {current_date.isoformat()}\n"
                    f"{count} entries so far ({elapsed} days remaining)"
                )
            except Exception:
                pass

    try:
        total = await scrape_history(
            db, client, telegram_user_id, start_date, end_date, on_progress=on_progress
        )
    except Exception as e:
        errors += 1
        await update.effective_chat.send_message(
            f"Import stopped with error: {e}\n"
            f"Imported {total} entries before the error.\n"
            "Analyzing what we have..."
        )

    pattern_count = await analyze_history(db, telegram_user_id)

    await update.effective_chat.send_message(
        f"Import complete!\n"
        f"Entries: {total}\n"
        f"Patterns found: {pattern_count}\n\n"
        "Try /today to see your predictions!"
    )
