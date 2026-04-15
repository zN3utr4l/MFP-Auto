from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.utility import copy_command, undo_command
from db.database import get_meal_entries, init_db, save_meal_entry, save_user
from db.models import MealEntry, User

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
        await save_user(conn, user)
        yield conn


def _make_update():
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(send_message=AsyncMock()),
    )
    return update, msg


def _make_context(db, client=None, args=None):
    user_data = {}
    if client is not None:
        user_data["mfp_client"] = client
    return SimpleNamespace(bot_data={"db": db}, user_data=user_data, args=args or [])


@pytest.mark.asyncio
async def test_undo_command_removes_best_matching_local_entry(db):
    today = date.today().isoformat()
    await save_meal_entry(db, MealEntry(
        telegram_user_id=1,
        date=today,
        day_of_week=date.today().weekday(),
        slot="breakfast",
        food_name="Oats",
        quantity="80g",
        mfp_food_id="111",
    ))
    await save_meal_entry(db, MealEntry(
        telegram_user_id=1,
        date=today,
        day_of_week=date.today().weekday(),
        slot="lunch",
        food_name="Oats",
        quantity="120g",
        mfp_food_id="111",
    ))
    await save_meal_entry(db, MealEntry(
        telegram_user_id=1,
        date=today,
        day_of_week=date.today().weekday(),
        slot="dinner",
        food_name="Eggs",
        quantity="2",
        mfp_food_id="222",
    ))

    client = MagicMock()
    client.get_recent_entries = AsyncMock(return_value=[{
        "uuid": "entry-1",
        "food_name": "Oats",
        "slot": "lunch",
        "meal_name": "Lunch",
        "mfp_food_id": "111",
    }])
    client.delete_entry = AsyncMock(return_value=True)

    update, message = _make_update()
    context = _make_context(db, client)

    with patch("bot.daily._ensure_client", new=AsyncMock(return_value=client)):
        await undo_command(update, context)

    remaining = await get_meal_entries(db, 1, today)
    remaining_pairs = {(entry.slot, entry.food_name) for entry in remaining}
    assert ("breakfast", "Oats") in remaining_pairs
    assert ("lunch", "Oats") not in remaining_pairs
    assert ("dinner", "Eggs") in remaining_pairs


@pytest.mark.asyncio
async def test_undo_command_explains_scope_to_user(db):
    client = MagicMock()
    client.get_recent_entries = AsyncMock(return_value=[{
        "uuid": "entry-1",
        "food_name": "Oats",
        "slot": "breakfast",
        "meal_name": "Breakfast",
        "mfp_food_id": "111",
    }])
    client.delete_entry = AsyncMock(return_value=True)

    update, message = _make_update()
    context = _make_context(db, client)

    with patch("bot.daily._ensure_client", new=AsyncMock(return_value=client)):
        await undo_command(update, context)

    sent = message.reply_text.await_args.args[0]
    assert "most recent" in sent.lower()
    assert "today" in sent.lower()
    assert "mfp" in sent.lower()


@pytest.mark.asyncio
async def test_copy_command_skips_slots_already_filled_in_mfp(db):
    yesterday = date.today() - timedelta(days=1)
    await save_meal_entry(db, MealEntry(
        telegram_user_id=1,
        date=yesterday.isoformat(),
        day_of_week=yesterday.weekday(),
        slot="breakfast",
        food_name="Oats",
        quantity="80g",
        mfp_food_id="111",
        serving_info='{"servings": 0.8, "unit": "g"}',
    ))

    client = MagicMock()
    client.add_entry = AsyncMock(return_value=True)

    status_msg = SimpleNamespace(edit_text=AsyncMock())
    update, message = _make_update()
    message.reply_text = AsyncMock(return_value=status_msg)
    context = _make_context(db, client, args=["yesterday"])

    with (
        patch("bot.daily._ensure_client", new=AsyncMock(return_value=client)),
        patch("bot.daily._fetch_mfp_filled_slots", new=AsyncMock(return_value={
            "breakfast": {"foods": ["Already logged"], "calories": 100, "protein": 10, "carbs": 10, "fat": 1},
        })),
        patch("bot.daily._send_macro_update", new=AsyncMock()),
    ):
        await copy_command(update, context)

    client.add_entry.assert_not_awaited()
    sent = status_msg.edit_text.await_args.args[0]
    assert "skipped" in sent.lower()
    assert "breakfast" in sent.lower()
