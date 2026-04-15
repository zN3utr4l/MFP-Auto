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


def _build_pattern_serving_info(food_names: list[str], serving_infos_raw: list[str]) -> list[dict]:
    """Build a list of per-food serving_info dicts from raw DB strings."""
    result = []
    for si_raw in serving_infos_raw:
        try:
            si = json.loads(si_raw) if isinstance(si_raw, str) else (si_raw or {})
        except (json.JSONDecodeError, TypeError):
            si = {}
        result.append(si)
    return result


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
            "serving_info": list,
        }).reset_index()

        # Count how often each combo appears
        combo_counter: Counter[str] = Counter()
        combo_details: dict[str, dict] = {}

        for _, day_row in daily_combos.iterrows():
            # Sort foods alphabetically and keep mfp_ids/serving_infos in sync
            sorted_items = sorted(
                zip(day_row["food_name"], day_row["mfp_food_id"], day_row["serving_info"]),
                key=lambda x: x[0],
            )
            sorted_names = [x[0] for x in sorted_items]
            sorted_ids = [x[1] for x in sorted_items]
            sorted_si = [x[2] for x in sorted_items]

            combo_key = json.dumps(sorted_names)
            weeks = _weeks_since(day_row["date"], now)
            decayed_weight = DECAY_RATE ** weeks

            combo_counter[combo_key] += decayed_weight

            if combo_key not in combo_details:
                combo_details[combo_key] = {
                    "food_names": sorted_names,
                    "mfp_food_ids": sorted_ids,
                    "serving_infos": sorted_si,
                    "last_date": day_row["date"],
                }
            elif day_row["date"] > combo_details[combo_key]["last_date"]:
                combo_details[combo_key]["last_date"] = day_row["date"]
                combo_details[combo_key]["mfp_food_ids"] = sorted_ids
                combo_details[combo_key]["serving_infos"] = sorted_si

        # Save patterns
        for combo_key, weight in combo_counter.most_common():
            details = combo_details[combo_key]
            # Build per-food serving_info dict keyed by food name
            serving_info = _build_pattern_serving_info(
                details["food_names"], details["serving_infos"]
            )
            pattern = MealPattern(
                telegram_user_id=telegram_user_id,
                slot=slot,
                day_type=day_type,
                food_combo=json.dumps(details["food_names"]),
                mfp_food_ids=json.dumps(details["mfp_food_ids"]),
                weight=round(weight, 4),
                last_confirmed=details["last_date"],
                serving_info=json.dumps(serving_info),
            )
            await save_meal_pattern(db, pattern)
            pattern_count += 1

    return pattern_count
