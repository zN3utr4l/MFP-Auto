from __future__ import annotations

import asyncio
from datetime import date, timedelta

import aiosqlite

from config import MFP_DEFAULT_MEALS, SCRAPE_RATE_LIMIT
from db.database import save_meal_entry
from db.models import MealEntry
from mfp.client import MfpClient


async def scrape_history(
    db: aiosqlite.Connection,
    client: MfpClient,
    telegram_user_id: int,
    start_date: date,
    end_date: date,
    on_progress: callable | None = None,
) -> int:
    """Scrape MFP diary from start_date to end_date inclusive. Returns total entries saved."""
    total = 0
    current = start_date

    while current <= end_date:
        meals = await client.get_day(current)
        day_of_week = current.weekday()  # 0=Mon

        for meal_data in meals:
            mfp_meal_name = meal_data["meal_name"]
            slot = MFP_DEFAULT_MEALS.get(mfp_meal_name, "morning_snack")

            for entry_data in meal_data["entries"]:
                entry = MealEntry(
                    telegram_user_id=telegram_user_id,
                    date=current.isoformat(),
                    day_of_week=day_of_week,
                    slot=slot,
                    food_name=entry_data["name"],
                    quantity=str(entry_data.get("quantity", "")),
                    mfp_food_id=str(entry_data.get("mfp_id", "")),
                    source="mfp_scrape",
                    synced_to_mfp=True,
                )
                await save_meal_entry(db, entry)
                total += 1

        if on_progress:
            await on_progress(current, total)

        current += timedelta(days=1)
        await asyncio.sleep(SCRAPE_RATE_LIMIT)

    return total
