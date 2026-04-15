from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_entry, get_unsynced_entries, mark_entry_synced
from db.models import MealEntry, User
from mfp.sync import retry_unsynced

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_retry_unsynced_marks_successful(db):
    entry = MealEntry(
        telegram_user_id=1, date="2026-04-10", day_of_week=3,
        slot="breakfast", food_name="Oats", quantity="80g",
        mfp_food_id="111", source="bot_confirm", synced_to_mfp=False,
    )
    entry_id = await save_meal_entry(db, entry)

    mock_client = MagicMock()
    mock_client.add_entry = AsyncMock(return_value=True)

    synced, failed, errors = await retry_unsynced(db, mock_client, telegram_user_id=1)
    assert synced == 1
    assert failed == 0

    unsynced = await get_unsynced_entries(db, 1)
    assert len(unsynced) == 0


@pytest.mark.asyncio
async def test_retry_unsynced_counts_failures(db):
    entry = MealEntry(
        telegram_user_id=1, date="2026-04-10", day_of_week=3,
        slot="breakfast", food_name="Oats", quantity="80g",
        mfp_food_id="111", source="bot_confirm", synced_to_mfp=False,
    )
    await save_meal_entry(db, entry)

    mock_client = MagicMock()
    mock_client.add_entry = AsyncMock(side_effect=Exception("MFP down"))

    synced, failed, errors = await retry_unsynced(db, mock_client, telegram_user_id=1)
    assert synced == 0
    assert failed == 1
    assert len(errors) == 1
    assert "Oats" in errors[0]


@pytest.mark.asyncio
async def test_retry_unsynced_reuses_serving_info(db):
    entry = MealEntry(
        telegram_user_id=1,
        date="2026-04-10",
        day_of_week=3,
        slot="breakfast",
        food_name="Oats",
        quantity="80g",
        mfp_food_id="111",
        source="bot_confirm",
        synced_to_mfp=False,
        serving_info='{"servings": 0.8, "serving_size_index": 4}',
    )
    await save_meal_entry(db, entry)

    mock_client = MagicMock()
    mock_client.add_entry = AsyncMock(return_value=True)

    synced, failed, errors = await retry_unsynced(db, mock_client, telegram_user_id=1)
    assert synced == 1
    assert failed == 0

    kwargs = mock_client.add_entry.await_args.kwargs
    assert kwargs["servings"] == 0.8
    assert kwargs["serving_size_index"] == 4
