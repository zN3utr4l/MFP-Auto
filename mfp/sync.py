from __future__ import annotations

import json
import logging

import aiosqlite

from db.database import get_unsynced_entries, mark_entry_synced
from mfp.client import MfpClient

logger = logging.getLogger(__name__)


async def retry_unsynced(
    db: aiosqlite.Connection,
    client: MfpClient,
    telegram_user_id: int,
) -> tuple[int, int, list[str]]:
    """Try to sync all unsynced entries to MFP.

    Returns (synced_count, failed_count, error_details).
    """
    entries = await get_unsynced_entries(db, telegram_user_id)
    synced = 0
    failed = 0
    errors: list[str] = []

    for entry in entries:
        try:
            serving_info = json.loads(entry.serving_info or "{}")
        except json.JSONDecodeError:
            serving_info = {}
        try:
            await client.add_entry(
                date_str=entry.date,
                meal_name=entry.slot,
                food_name=entry.food_name,
                mfp_food_id=entry.mfp_food_id,
                servings=serving_info.get("servings", 1.0),
                serving_size_index=serving_info.get("serving_size_index"),
                fallback_serving=serving_info,
            )
            await mark_entry_synced(db, entry.id)
            synced += 1
        except Exception as exc:
            logger.error("Sync failed for '%s' (id=%s): %s", entry.food_name, entry.mfp_food_id, exc)
            errors.append(f"{entry.food_name}: {exc}")
            failed += 1

    return synced, failed, errors
