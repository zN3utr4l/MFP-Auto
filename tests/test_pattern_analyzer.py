import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_entry, get_meal_patterns
from db.models import MealEntry, User
from engine.pattern_analyzer import analyze_history

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


async def _insert_entries(db, slot, food_name, dates, mfp_food_id="111"):
    for d in dates:
        from datetime import date as dt_date
        parsed = dt_date.fromisoformat(d)
        entry = MealEntry(
            telegram_user_id=1,
            date=d,
            day_of_week=parsed.weekday(),
            slot=slot,
            food_name=food_name,
            quantity="1",
            mfp_food_id=mfp_food_id,
            source="mfp_scrape",
        )
        await save_meal_entry(db, entry)


@pytest.mark.asyncio
async def test_analyze_creates_patterns(db):
    weekday_dates = ["2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"]
    await _insert_entries(db, "breakfast", "Oats 80g", weekday_dates)

    await analyze_history(db, telegram_user_id=1)

    patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekday")
    assert len(patterns) >= 1
    assert patterns[0].get_food_combo_list() == ["Oats 80g"]
    assert patterns[0].weight > 0


@pytest.mark.asyncio
async def test_analyze_distinguishes_weekday_weekend(db):
    await _insert_entries(db, "breakfast", "Oats 80g", ["2026-04-06", "2026-04-07", "2026-04-08"])  # Mon-Wed
    await _insert_entries(db, "breakfast", "Pancakes", ["2026-04-04", "2026-04-05"])  # Sat-Sun

    await analyze_history(db, telegram_user_id=1)

    weekday_patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekday")
    weekend_patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekend")

    assert any("Oats" in p.get_food_combo_list()[0] for p in weekday_patterns)
    assert any("Pancakes" in p.get_food_combo_list()[0] for p in weekend_patterns)
