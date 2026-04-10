import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, get_meal_entries
from db.models import User
from mfp.scraper import scrape_history

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
async def test_scrape_history_saves_entries(db):
    mock_client = MagicMock()

    async def fake_get_day(d):
        return [
            {
                "meal_name": "Breakfast",
                "entries": [
                    {"name": "Oats 80g", "quantity": 1.0, "mfp_id": 111},
                ],
            },
            {
                "meal_name": "Snacks",
                "entries": [
                    {"name": "Almonds 30g", "quantity": 1.0, "mfp_id": 222},
                ],
            },
        ]

    mock_client.get_day = fake_get_day

    start = date(2026, 4, 8)
    end = date(2026, 4, 9)
    count = await scrape_history(db, mock_client, telegram_user_id=1, start_date=start, end_date=end)

    assert count == 4  # 2 entries x 2 days

    entries = await get_meal_entries(db, telegram_user_id=1, date="2026-04-08")
    assert len(entries) == 2
    assert entries[0].source == "mfp_scrape"


@pytest.mark.asyncio
async def test_scrape_history_maps_known_meals(db):
    mock_client = MagicMock()

    async def fake_get_day(d):
        return [{"meal_name": "Lunch", "entries": [{"name": "Rice 100g", "quantity": 1.0, "mfp_id": 333}]}]

    mock_client.get_day = fake_get_day

    count = await scrape_history(db, mock_client, telegram_user_id=1, start_date=date(2026, 4, 10), end_date=date(2026, 4, 10))

    entries = await get_meal_entries(db, telegram_user_id=1, date="2026-04-10", slot="lunch")
    assert len(entries) == 1
