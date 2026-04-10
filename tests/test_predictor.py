import json
from datetime import date

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_pattern
from db.models import MealPattern, User
from engine.predictor import predict_day

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
async def test_predict_day_returns_high_confidence_slot(db):
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Oats 80g", "Banana"]', mfp_food_ids='["111", "222"]',
        weight=10.0, last_confirmed="2026-04-10",
    ))

    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    breakfast = predictions["breakfast"]
    assert breakfast["confidence"] == "high"
    assert breakfast["top"]["foods"] == ["Oats 80g", "Banana"]


@pytest.mark.asyncio
async def test_predict_day_returns_alternatives_for_variable_slot(db):
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Chicken 200g"]', mfp_food_ids='["333"]',
        weight=3.0, last_confirmed="2026-04-09",
    ))
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Tuna 160g"]', mfp_food_ids='["444"]',
        weight=2.5, last_confirmed="2026-04-08",
    ))
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Pasta 80g"]', mfp_food_ids='["555"]',
        weight=1.0, last_confirmed="2026-04-07",
    ))

    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    lunch = predictions["lunch"]
    assert lunch["confidence"] == "low"
    assert len(lunch["alternatives"]) == 3


@pytest.mark.asyncio
async def test_predict_day_returns_empty_for_no_patterns(db):
    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    breakfast = predictions["breakfast"]
    assert breakfast["confidence"] == "none"
    assert breakfast["top"] is None
    assert breakfast["alternatives"] == []
