from __future__ import annotations

from datetime import date

import aiosqlite

from config import HIGH_CONFIDENCE_THRESHOLD, MAX_ALTERNATIVES, MEAL_SLOTS
from db.database import get_meal_patterns


def _day_type(target_date: date) -> str:
    return "weekend" if target_date.weekday() >= 5 else "weekday"


async def predict_day(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    target_date: date,
) -> dict[str, dict]:
    """Return predictions for each slot on target_date.

    Returns dict keyed by slot name. Each value:
    {
        "confidence": "high" | "low" | "none",
        "top": {"foods": [...], "mfp_ids": [...], "pattern_id": int} | None,
        "alternatives": [{"foods": [...], "mfp_ids": [...], "pattern_id": int}, ...],
    }
    """
    day_type = _day_type(target_date)
    predictions: dict[str, dict] = {}

    for slot in MEAL_SLOTS:
        patterns = await get_meal_patterns(db, telegram_user_id, slot, day_type)

        if not patterns:
            predictions[slot] = {"confidence": "none", "top": None, "alternatives": []}
            continue

        total_weight = sum(p.weight for p in patterns)
        top = patterns[0]
        top_ratio = top.weight / total_weight if total_weight > 0 else 0

        top_entry = {
            "foods": top.get_food_combo_list(),
            "mfp_ids": top.get_mfp_food_ids_list(),
            "pattern_id": top.id,
        }

        alternatives = [
            {
                "foods": p.get_food_combo_list(),
                "mfp_ids": p.get_mfp_food_ids_list(),
                "pattern_id": p.id,
            }
            for p in patterns[:MAX_ALTERNATIVES]
        ]

        if top_ratio >= HIGH_CONFIDENCE_THRESHOLD:
            predictions[slot] = {"confidence": "high", "top": top_entry, "alternatives": alternatives}
        else:
            predictions[slot] = {"confidence": "low", "top": top_entry, "alternatives": alternatives}

    return predictions
