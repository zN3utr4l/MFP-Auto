"""Integration tests against the real Telegram Bot API.

Requires .env with:
  TELEGRAM_BOT_TOKEN  — real bot token from BotFather
  TELEGRAM_TEST_CHAT_ID — numeric chat ID to send test messages to

All tests are skipped if these env vars are missing.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_TEST_CHAT_ID", "")

needs_telegram = pytest.mark.skipif(
    not BOT_TOKEN or BOT_TOKEN == "test-token-for-pytest" or not CHAT_ID,
    reason="TELEGRAM_BOT_TOKEN and TELEGRAM_TEST_CHAT_ID required",
)


def _bot():
    """Create a standalone telegram.Bot (no Application overhead)."""
    from telegram import Bot

    return Bot(token=BOT_TOKEN)


# ── Identity ──────────────────────────────────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_bot_get_me():
    """Bot token is valid and getMe returns bot info."""
    bot = _bot()
    me = await bot.get_me()
    assert me.is_bot is True
    assert me.username  # has a username
    print(f"  Bot: @{me.username} (id={me.id})")


# ── Messaging ─────────────────────────────────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_send_text_message():
    """Bot can send a plain text message to the test chat."""
    bot = _bot()
    msg = await bot.send_message(chat_id=int(CHAT_ID), text="Integration test: plain text")
    assert msg.text == "Integration test: plain text"
    assert msg.chat.id == int(CHAT_ID)
    # clean up
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


@needs_telegram
@pytest.mark.asyncio
async def test_send_markdown_message():
    """Bot can send a Markdown-formatted message (used by slot messages)."""
    bot = _bot()
    text = "☕ *Breakfast*\nOatmeal 80g, Banana"
    msg = await bot.send_message(
        chat_id=int(CHAT_ID), text=text, parse_mode="Markdown"
    )
    assert msg.text  # parsed without error
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


# ── Inline Keyboards ─────────────────────────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_send_inline_keyboard():
    """Bot can send a message with inline keyboard buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    bot = _bot()
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="test:confirm"),
            InlineKeyboardButton("⏭ Skip", callback_data="test:skip"),
        ]
    ])
    msg = await bot.send_message(
        chat_id=int(CHAT_ID),
        text="Integration test: inline keyboard",
        reply_markup=kb,
    )
    assert msg.reply_markup is not None
    assert len(msg.reply_markup.inline_keyboard[0]) == 2
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


@needs_telegram
@pytest.mark.asyncio
async def test_edit_message_text():
    """Bot can edit an existing message (used for progress updates)."""
    bot = _bot()
    msg = await bot.send_message(chat_id=int(CHAT_ID), text="Before edit")
    edited = await bot.edit_message_text(
        chat_id=int(CHAT_ID),
        message_id=msg.message_id,
        text="After edit",
    )
    assert edited.text == "After edit"
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


@needs_telegram
@pytest.mark.asyncio
async def test_delete_message():
    """Bot can delete a message (used for /token security)."""
    bot = _bot()
    msg = await bot.send_message(chat_id=int(CHAT_ID), text="To be deleted")
    result = await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)
    assert result is True


# ── Bot Commands ──────────────────────────────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_set_bot_commands():
    """Bot can register its commands with Telegram."""
    from telegram import BotCommand

    bot = _bot()
    commands = [
        BotCommand("start", "Connect to MFP"),
        BotCommand("token", "Set MFP auth token"),
        BotCommand("setup", "Register your typical foods"),
        BotCommand("today", "Plan today's meals"),
        BotCommand("tomorrow", "Plan tomorrow's meals"),
        BotCommand("day", "Plan a specific day"),
        BotCommand("week", "Plan the whole week"),
        BotCommand("macros", "Show remaining daily macros"),
        BotCommand("suggest", "Suggest foods that fit your macros"),
        BotCommand("copy", "Copy meals from another day"),
        BotCommand("history", "7-day macro history"),
        BotCommand("status", "Weekly status"),
        BotCommand("undo", "Remove last entry"),
        BotCommand("retry", "Retry failed syncs"),
    ]
    result = await bot.set_my_commands(commands)
    assert result is True

    registered = await bot.get_my_commands()
    registered_names = {c.command for c in registered}
    assert "start" in registered_names
    assert "setup" in registered_names
    assert "macros" in registered_names
    assert "suggest" in registered_names
    assert "copy" in registered_names
    assert "history" in registered_names


# ── Application Lifecycle ─────────────────────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_application_initializes():
    """Full Application can initialize (DB, handlers) without error."""
    import aiosqlite
    from telegram.ext import Application, CommandHandler

    from db.database import get_db

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Simulate post_init: create in-memory DB
    await app.initialize()
    db = await get_db(":memory:")
    app.bot_data["db"] = db

    # Verify bot is alive
    me = await app.bot.get_me()
    assert me.is_bot

    # Clean up
    await db.close()
    await app.shutdown()


# ── Real Keyboards from bot/keyboards.py ─────────────────────────


@needs_telegram
@pytest.mark.asyncio
async def test_send_real_slot_keyboard_high():
    """Send a real high-confidence slot message with keyboard."""
    from bot.keyboards import slot_keyboard_high
    from bot.messages import format_slot_message

    bot = _bot()
    prediction = {
        "confidence": "high",
        "top": {"foods": ["Oatmeal 80g", "Banana"], "mfp_ids": ["111", "222"], "pattern_id": 1},
        "alternatives": [],
    }
    text = format_slot_message("breakfast", prediction)
    kb = slot_keyboard_high("breakfast", 1)
    msg = await bot.send_message(
        chat_id=int(CHAT_ID), text=text, reply_markup=kb, parse_mode="Markdown"
    )
    assert msg.reply_markup is not None
    buttons = msg.reply_markup.inline_keyboard[0]
    assert any("Confirm" in b.text for b in buttons)
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


@needs_telegram
@pytest.mark.asyncio
async def test_send_real_slot_keyboard_none():
    """Send a no-pattern slot message with search/skip keyboard."""
    from bot.keyboards import slot_keyboard_none
    from bot.messages import format_slot_message

    bot = _bot()
    prediction = {"confidence": "none", "top": None, "alternatives": []}
    text = format_slot_message("pre_workout", prediction)
    kb = slot_keyboard_none("pre_workout")
    msg = await bot.send_message(
        chat_id=int(CHAT_ID), text=text, reply_markup=kb, parse_mode="Markdown"
    )
    assert msg.reply_markup is not None
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)


@needs_telegram
@pytest.mark.asyncio
async def test_send_day_header():
    """Send a real day header message."""
    from bot.messages import format_day_header

    bot = _bot()
    text = format_day_header("2026-04-13", 1, 7)
    msg = await bot.send_message(chat_id=int(CHAT_ID), text=text, parse_mode="Markdown")
    assert "Monday" in msg.text or "📅" in msg.text
    await bot.delete_message(chat_id=int(CHAT_ID), message_id=msg.message_id)
