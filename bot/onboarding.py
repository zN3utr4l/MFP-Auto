from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from db.database import encrypt_password, get_user, save_user
from db.models import User
from mfp.client import MfpClient

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
        "(starts with `{\"access_token\":...}`). "
        "Select ALL the text and copy it.\n\n"
        "*Step 4:* Come back here and send:\n"
        "`/token <paste the text here>`\n\n"
        "Your token will be deleted from chat immediately for security.",
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
    existing = await get_user(db, update.effective_user.id)
    user = User(
        telegram_user_id=update.effective_user.id,
        mfp_username=username,
        mfp_password_encrypted=encrypted_token,
        onboarding_done=True,
    )
    if existing:
        user.is_premium = existing.is_premium
    await save_user(db, user)

    context.user_data["mfp_client"] = client

    await status_msg.edit_text(
        f"Connected as *{username}* on MFP!\n\n"
        "*What's next?*\n\n"
        "*Option A — Quick setup (recommended):*\n"
        "Send /setup and I'll ask you to search for the foods you "
        "eat regularly (the exact ones you use on MFP, barcodes included). "
        "Takes 5 min, predictions work from day 1.\n\n"
        "*Option B — Jump right in:*\n"
        "Send /today and start logging. I'll learn your preferences "
        "as you go. Predictions improve after 2-3 days.",
        parse_mode="Markdown",
    )
