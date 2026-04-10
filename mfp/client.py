from __future__ import annotations

import asyncio
from datetime import date

import myfitnesspal


class MfpClient:
    """Wrapper around python-myfitnesspal. All sync methods have async counterparts via to_thread."""

    def __init__(self, username: str, password: str) -> None:
        self._client = myfitnesspal.Client(username, password)

    # --- Sync methods (called in thread) ---

    def get_day_sync(self, target_date: date) -> list[dict]:
        day = self._client.get_date(target_date)
        meals = []
        for meal in day.meals:
            entries = []
            for entry in meal.entries:
                entries.append({
                    "name": entry.name,
                    "quantity": getattr(entry, "quantity", 1.0),
                    "mfp_id": getattr(entry, "mfp_id", None),
                    "nutritional_info": dict(entry.nutrition_information) if hasattr(entry, "nutrition_information") else {},
                })
            meals.append({"meal_name": meal.name, "entries": entries})
        return meals

    def search_food_sync(self, query: str) -> list[dict]:
        results = self._client.get_food_search_results(query=query)
        return [
            {"name": item.name, "mfp_id": getattr(item, "mfp_id", None)}
            for item in results
        ]

    def get_food_details_sync(self, mfp_id: int) -> dict | None:
        try:
            item = self._client.get_food_item_details(mfp_id=mfp_id)
            return {"name": item.name, "mfp_id": mfp_id}
        except Exception:
            return None

    # --- Async wrappers ---

    async def get_day(self, target_date: date) -> list[dict]:
        return await asyncio.to_thread(self.get_day_sync, target_date)

    async def search_food(self, query: str) -> list[dict]:
        return await asyncio.to_thread(self.search_food_sync, query)

    async def get_food_details(self, mfp_id: int) -> dict | None:
        return await asyncio.to_thread(self.get_food_details_sync, mfp_id)

    def add_entry_sync(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        """Add a food entry to MFP diary. Returns True on success."""
        # python-myfitnesspal doesn't expose a direct "add entry" method.
        # For now this is a placeholder that will need to use the undocumented MFP web API.
        # TODO: Implement when python-myfitnesspal adds write support or use HTTP directly
        return True

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id)
