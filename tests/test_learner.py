import json
from datetime import date

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_pattern, get_meal_patterns
from db.models import MealPattern, User
from engine.learner import on_confirm, on_replace

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
async def test_on_confirm_increases_weight(db):
    pid = await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Oats 80g"]', mfp_food_ids='["111"]',
        weight=5.0, last_confirmed="2026-04-09",
    ))

    await on_confirm(db, pattern_id=pid, confirmed_date="2026-04-10")

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert patterns[0].weight == 6.0
    assert patterns[0].last_confirmed == "2026-04-10"


@pytest.mark.asyncio
async def test_on_replace_creates_new_pattern_if_missing(db):
    await on_replace(
        db,
        telegram_user_id=1,
        slot="breakfast",
        day_type="weekday",
        new_foods=["Yogurt 170g", "Granola 50g"],
        new_mfp_ids=["888", "999"],
        confirmed_date="2026-04-10",
    )

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert len(patterns) == 1
    assert patterns[0].get_food_combo_list() == ["Yogurt 170g", "Granola 50g"]
    assert patterns[0].weight == 1.0


@pytest.mark.asyncio
async def test_on_replace_boosts_existing_pattern(db):
    pid = await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Yogurt 170g", "Granola 50g"]', mfp_food_ids='["888", "999"]',
        weight=2.0, last_confirmed="2026-04-08",
    ))

    await on_replace(
        db,
        telegram_user_id=1,
        slot="breakfast",
        day_type="weekday",
        new_foods=["Yogurt 170g", "Granola 50g"],
        new_mfp_ids=["888", "999"],
        confirmed_date="2026-04-10",
    )

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert patterns[0].weight == 3.0
