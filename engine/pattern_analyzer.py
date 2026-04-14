from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

import aiosqlite
import pandas as pd

from config import DECAY_RATE
from db.database import save_meal_pattern
from db.models import MealPattern


def _weeks_since(ref_date: str, now: date | None = None) -> float:
    now = now or date.today()
    delta = now - date.fromisoformat(ref_date)
    return max(delta.days / 7.0, 0)


def _day_type(day_of_week) -> str:
    """Return 'weekday' or 'weekend'."""
    return "weekend" if int(day_of_week) >= 5 else "weekday"


async def analyze_history(db: aiosqlite.Connection, telegram_user_id: int) -> int:
    """Analyze meals_history and populate meal_patterns. Returns number of patterns created."""

    # Clear existing patterns for this user (full recalculation)
    await db.execute("DELETE FROM meal_patterns WHERE telegram_user_id = ?", (telegram_user_id,))
    await db.commit()

    # Load all history into a DataFrame
    rows = []
    async with db.execute(
        "SELECT * FROM meals_history WHERE telegram_user_id = ?", (telegram_user_id,)
    ) as cursor:
        async for row in cursor:
            rows.append(dict(row))

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    df["day_type"] = df["day_of_week"].apply(_day_type)
    now = date.today()

    pattern_count = 0

    # Group by (slot, day_type) and find recurring food combos
    for (slot, day_type), group in df.groupby(["slot", "day_type"]):
        # Group by date to get the food combo per day
        daily_combos = group.groupby("date").agg({
            "food_name": list,
            "mfp_food_id": list,
        }).reset_index()

        # Count how often each combo appears
        combo_counter: Counter[str] = Counter()
        combo_details: dict[str, dict] = {}

        for _, day_row in daily_combos.iterrows():
            combo_key = json.dumps(sorted(day_row["food_name"]))
            weeks = _weeks_since(day_row["date"], now)
            decayed_weight = DECAY_RATE ** weeks

            combo_counter[combo_key] += decayed_weight

            if combo_key not in combo_details:
                combo_details[combo_key] = {
                    "food_names": sorted(day_row["food_name"]),
                    "mfp_food_ids": day_row["mfp_food_id"],
                    "last_date": day_row["date"],
                }
            elif day_row["date"] > combo_details[combo_key]["last_date"]:
                combo_details[combo_key]["last_date"] = day_row["date"]
                combo_details[combo_key]["mfp_food_ids"] = day_row["mfp_food_id"]

        # Save patterns
        for combo_key, weight in combo_counter.most_common():
            details = combo_details[combo_key]
            pattern = MealPattern(
                telegram_user_id=telegram_user_id,
                slot=slot,
                day_type=day_type,
                food_combo=json.dumps(details["food_names"]),
                mfp_food_ids=json.dumps(details["mfp_food_ids"]),
                weight=round(weight, 4),
                last_confirmed=details["last_date"],
            )
            await save_meal_pattern(db, pattern)
            pattern_count += 1

    return pattern_count
