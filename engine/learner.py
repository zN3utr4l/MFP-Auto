from __future__ import annotations

import json

import aiosqlite

from db.database import get_meal_patterns, save_meal_pattern, update_pattern_weight
from db.models import MealPattern


async def on_confirm(db: aiosqlite.Connection, pattern_id: int, confirmed_date: str) -> None:
    """User confirmed a predicted meal. Increase its weight by 1."""
    async with db.execute("SELECT weight FROM meal_patterns WHERE id = ?", (pattern_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    new_weight = row["weight"] + 1.0
    await update_pattern_weight(db, pattern_id, new_weight, confirmed_date)


async def on_replace(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    slot: str,
    day_type: str,
    new_foods: list[str],
    new_mfp_ids: list[str],
    confirmed_date: str,
) -> int:
    """User replaced a prediction with a different meal. Boost or create the replacement pattern.
    Returns the pattern_id of the boosted/created pattern."""
    combo_key = json.dumps(sorted(new_foods))

    # Check if this combo already exists
    patterns = await get_meal_patterns(db, telegram_user_id, slot, day_type)
    for p in patterns:
        if json.dumps(sorted(p.get_food_combo_list())) == combo_key:
            new_weight = p.weight + 1.0
            await update_pattern_weight(db, p.id, new_weight, confirmed_date)
            return p.id

    # Create new pattern
    pattern = MealPattern(
        telegram_user_id=telegram_user_id,
        slot=slot,
        day_type=day_type,
        food_combo=json.dumps(new_foods),
        mfp_food_ids=json.dumps(new_mfp_ids),
        weight=1.0,
        last_confirmed=confirmed_date,
    )
    return await save_meal_pattern(db, pattern)
