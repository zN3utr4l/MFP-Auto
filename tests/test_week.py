from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.week import _start_next_day
from db.database import init_db, save_user
from db.models import User

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_start_next_day_skips_days_already_filled_in_mfp(db):
    today = date.today()
    tomorrow = today + timedelta(days=1)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(send_message=AsyncMock()),
    )
    context = SimpleNamespace(
        bot_data={"db": db},
        user_data={
            "mfp_client": object(),
            "week_mode": {
                "wp_id": 1,
                "start": today,
                "end": tomorrow,
                "current": today,
            },
        },
    )

    with (
        patch("bot.week.start_day_flow", new=AsyncMock()) as start_day_flow,
        patch("bot.daily._fetch_mfp_filled_slots", new=AsyncMock(side_effect=[
            {
                "breakfast": {},
                "lunch": {},
                "dinner": {},
                "snacks": {},
            },
            {},
        ])),
    ):
        await _start_next_day(update, context)

    start_day_flow.assert_awaited_once()
    assert start_day_flow.await_args.args[2] == tomorrow
