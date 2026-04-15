import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.daily import DAY_NAMES, _get_target_date, slot_callback
from db.database import init_db, save_user
from db.models import MealPattern, User

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


def _make_update(callback_data: str):
    query = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(delete=AsyncMock()),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(send_message=AsyncMock()),
    )
    return update, query


def _make_context(db, client=None):
    return SimpleNamespace(
        bot_data={"db": db},
        user_data={"mfp_client": client} if client else {},
    )


def test_get_target_date_returns_correct_day():
    target = _get_target_date("Mon")
    assert target.weekday() == 0  # Monday


def test_get_target_date_handles_short_names():
    for name, dow in DAY_NAMES.items():
        target = _get_target_date(name)
        assert target.weekday() == dow


@pytest.mark.asyncio
async def test_slot_callback_rejects_stale_flow_id_same_date(db):
    update, query = _make_update("search:breakfast:2026-04-14:oldflow")
    context = _make_context(db)
    context.user_data["current_day"] = {
        "date": "2026-04-14",
        "flow_id": "newflow",
        "all_predictions": {},
    }

    await slot_callback(update, context)

    query.edit_message_text.assert_awaited_once()
    assert "expired" in query.edit_message_text.await_args.args[0].lower()
    assert "search_slot" not in context.user_data


@pytest.mark.asyncio
async def test_slot_callback_pick_uses_alternative_serving_info(db):
    client = MagicMock()
    client.add_entry = AsyncMock(return_value=True)
    update, query = _make_update("pick:lunch:42:2026-04-14:flow42")
    context = _make_context(db, client)
    context.user_data["current_day"] = {
        "date": "2026-04-14",
        "flow_id": "flow42",
        "all_predictions": {
            "lunch": {
                "confidence": "low",
                "top": None,
                "alternatives": [
                    {
                        "foods": ["Chicken 200g"],
                        "mfp_ids": ["333"],
                        "pattern_id": 42,
                        "serving_info": [{"servings": 1.5, "serving_size_index": 2}],
                    }
                ],
            }
        },
        "confirmed": 0,
        "skipped": 0,
    }

    with (
        patch("bot.daily.on_replace", new=AsyncMock()),
        patch("bot.daily._send_macro_update", new=AsyncMock()),
        patch("bot.daily._send_next_slot", new=AsyncMock(return_value=True)),
    ):
        await slot_callback(update, context)

    kwargs = client.add_entry.await_args.kwargs
    assert kwargs["servings"] == 1.5
    assert kwargs["serving_size_index"] == 2


@pytest.mark.asyncio
async def test_slot_callback_confirm_reports_sync_failure(db):
    client = MagicMock()
    client.add_entry = AsyncMock(side_effect=Exception("MFP down"))
    update, query = _make_update("confirm:breakfast:7:2026-04-14:flow7")
    context = _make_context(db, client)
    context.user_data["current_day"] = {
        "date": "2026-04-14",
        "flow_id": "flow7",
        "all_predictions": {
            "breakfast": {
                "confidence": "high",
                "top": {
                    "foods": ["Oats"],
                    "mfp_ids": ["111"],
                    "pattern_id": 7,
                    "serving_info": [{"servings": 0.8, "serving_size_index": 4}],
                },
                "alternatives": [],
            }
        },
        "confirmed": 0,
        "skipped": 0,
    }

    with (
        patch("bot.daily.on_confirm", new=AsyncMock()),
        patch("bot.daily._send_macro_update", new=AsyncMock()) as macro_update,
        patch("bot.daily._send_next_slot", new=AsyncMock(return_value=True)),
    ):
        await slot_callback(update, context)

    query.edit_message_text.assert_awaited_once()
    assert "saved locally" in query.edit_message_text.await_args.args[0].lower()
    macro_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_slot_callback_search_uses_slot_label(db):
    update, query = _make_update("search:snacks:2026-04-14:flow9")
    context = _make_context(db)
    context.user_data["current_day"] = {
        "date": "2026-04-14",
        "flow_id": "flow9",
        "all_predictions": {
            "snacks": {"confidence": "none", "top": None, "alternatives": []},
        },
    }

    await slot_callback(update, context)

    query.edit_message_text.assert_awaited_once()
    assert "Snacks" in query.edit_message_text.await_args.args[0]
