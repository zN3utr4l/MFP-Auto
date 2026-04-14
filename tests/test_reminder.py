import pytest
import pytest_asyncio
import aiosqlite
from datetime import date
from types import SimpleNamespace

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
    assert count == 4  # breakfast, lunch, dinner, snacks


@pytest.mark.asyncio
async def test_count_empty_slots_partial(db):
    from bot.reminder import _count_empty_slots

    user = User(telegram_user_id=12345, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
    await save_user(db, user)

    entry = MealEntry(telegram_user_id=12345, date=date.today().isoformat(), day_of_week=0,
                      slot="breakfast", food_name="Oats", quantity="80g")
    await save_meal_entry(db, entry)
    count = await _count_empty_slots(db, 12345, date.today())
    assert count == 3  # lunch, dinner, snacks still empty


def test_schedule_reminders_uses_rome_timezone():
    from bot.reminder import schedule_reminders

    run_daily = lambda *args, **kwargs: None
    application = SimpleNamespace(job_queue=SimpleNamespace(run_daily=run_daily))

    called = {}

    def capture(callback, time, name):
        called["time"] = time
        called["name"] = name

    application.job_queue.run_daily = capture

    schedule_reminders(application)

    assert called["name"] == "daily_reminder"
    assert getattr(called["time"].tzinfo, "key", None) == "Europe/Rome"
