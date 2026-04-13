import pytest
import pytest_asyncio
import aiosqlite
from datetime import date

from db.database import init_db, save_user, save_meal_entry
from db.models import User, MealEntry


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_count_empty_slots_all_empty(db):
    from bot.reminder import _count_empty_slots

    user = User(telegram_user_id=12345, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
    await save_user(db, user)

    count = await _count_empty_slots(db, 12345, date.today())
    assert count == 7


@pytest.mark.asyncio
async def test_count_empty_slots_partial(db):
    from bot.reminder import _count_empty_slots

    user = User(telegram_user_id=12345, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
    await save_user(db, user)

    entry = MealEntry(telegram_user_id=12345, date=date.today().isoformat(), day_of_week=0,
                      slot="breakfast", food_name="Oats", quantity="80g")
    await save_meal_entry(db, entry)
    count = await _count_empty_slots(db, 12345, date.today())
    assert count == 6
