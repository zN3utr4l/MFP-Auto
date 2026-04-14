from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from urllib import parse

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Bot slot name → MFP meal_position integer
_SLOT_TO_MEAL_POSITION: dict[str, int] = {
    "breakfast": 0,
    "morning_snack": 3,
    "lunch": 1,
    "afternoon_snack": 3,
    "pre_workout": 3,
    "post_workout": 3,
    "dinner": 2,
}


class MfpClient:
    """MFP client using auth token from browser session. Uses MFP JSON API."""

    API_URL = "https://api.myfitnesspal.com/"

    def __init__(self, access_token: str, user_id: str) -> None:
        self._access_token = access_token
        self._user_id = user_id
        self.session = curl_requests.Session(impersonate="chrome")
        self._username: str | None = None

    @classmethod
    def from_auth_json(cls, auth_json: str) -> "MfpClient":
        """Create client from the JSON returned by /user/auth_token?refresh=true"""
        data = json.loads(auth_json)
        return cls(data["access_token"], data["user_id"])

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "mfp-client-id": "mfp-main-js",
            "mfp-user-id": self._user_id,
            "Accept": "application/json",
        }

    def _api_get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict:
        """Make an authenticated GET to the MFP API."""
        qs = parse.urlencode(params) if params else ""
        url = f"{self.API_URL}{path}" + (f"?{qs}" if qs else "")
        resp = self.session.get(url, headers=self._api_headers())
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path: str, payload: dict) -> dict:
        """Make an authenticated POST to the MFP API."""
        url = f"{self.API_URL}{path}"
        headers = {**self._api_headers(), "Content-Type": "application/json"}
        resp = self.session.post(url, headers=headers, json=payload)
        if not resp.ok:
            logger.error("POST %s → %s: %s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()

    # --- User info ---

    def get_username_sync(self) -> str:
        if self._username:
            return self._username
        data = self._api_get(f"v2/users/{self._user_id}", [("fields[]", "account")])
        self._username = data["item"]["username"]
        return self._username

    def validate_sync(self) -> str:
        """Validate the token. Returns username on success."""
        return self.get_username_sync()

    # --- Nutrition goals ---

    def get_nutrient_goals_sync(self) -> dict:
        """Fetch daily macro goals. Returns {calories, protein, carbs, fat}."""
        data = self._api_get("v2/nutrient-goals")
        items = data.get("items", [])
        if not items:
            return {}
        # Use Monday's goals as the default (they're the same every day for most users)
        daily = items[0].get("daily_goals", [])
        if not daily:
            return {}
        goals = daily[0]
        energy = goals.get("energy", {})
        return {
            "calories": energy.get("value", 0) if isinstance(energy, dict) else 0,
            "protein": goals.get("protein", 0),
            "carbs": goals.get("carbohydrates", 0),
            "fat": goals.get("fat", 0),
        }

    def get_day_totals_sync(self, target_date: date) -> dict:
        """Sum up the day's nutritional totals from diary. Returns {calories, protein, carbs, fat}."""
        date_str = target_date.strftime("%Y-%m-%d")
        data = self._api_get("v2/diary", [
            ("entry_date", date_str),
            ("fields[]", "nutritional_contents"),
        ])
        total = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
        for item in data.get("items", []):
            nc = item.get("nutritional_contents", {})
            total["protein"] += nc.get("protein", 0)
            total["carbs"] += nc.get("carbohydrates", 0)
            total["fat"] += nc.get("fat", 0)
            energy = nc.get("energy", {})
            total["calories"] += energy.get("value", 0) if isinstance(energy, dict) else 0
        return total

    async def get_nutrient_goals(self) -> dict:
        return await asyncio.to_thread(self.get_nutrient_goals_sync)

    async def get_day_totals(self, target_date: date) -> dict:
        return await asyncio.to_thread(self.get_day_totals_sync, target_date)

    # --- Read diary ---

    def get_day_sync(self, target_date: date) -> list[dict]:
        """Get meals for a date. Returns list of {meal_name, entries}.

        Each entry: {name, quantity, mfp_id, nutritional_info}.
        Requests individual diary entries from the API; falls back to
        meal-level summaries when entries aren't available.
        """
        date_str = target_date.strftime("%Y-%m-%d")
        data = self._api_get("v2/diary", [
            ("entry_date", date_str),
            ("fields[]", "nutritional_contents"),
            ("fields[]", "diary_entries"),
        ])

        logger.debug("MFP diary raw response keys: %s", list(data.keys()))

        # First pass: collect diary_entry items keyed by parent meal
        meal_entries: dict[str, list[dict]] = {}
        meal_order: list[str] = []

        for item in data.get("items", []):
            item_type = item.get("type", "")

            if item_type == "diary_meal":
                meal_name = item.get("diary_meal", "Unknown")
                if meal_name not in meal_entries:
                    meal_entries[meal_name] = []
                    meal_order.append(meal_name)

                # Check for nested diary_entries inside the meal item
                for de in item.get("diary_entries", []):
                    entry = self._parse_diary_entry(de)
                    if entry:
                        meal_entries[meal_name].append(entry)

            elif item_type == "diary_entry":
                # Top-level diary_entry — associate with its meal
                meal_name = item.get("diary_meal", "Unknown")
                if meal_name not in meal_entries:
                    meal_entries[meal_name] = []
                    meal_order.append(meal_name)
                entry = self._parse_diary_entry(item)
                if entry:
                    meal_entries[meal_name].append(entry)

        # Fallback: if no individual entries were found, use meal-level summaries
        if not any(meal_entries.values()):
            logger.info("No individual diary entries found, falling back to meal summaries")
            for item in data.get("items", []):
                if item.get("type") != "diary_meal":
                    continue
                meal_name = item.get("diary_meal", "Unknown")
                nutrition = item.get("nutritional_contents", {})
                energy = nutrition.get("energy", {})
                calories = energy.get("value", 0) if isinstance(energy, dict) else 0
                if calories > 0:
                    if meal_name not in meal_entries:
                        meal_entries[meal_name] = []
                        meal_order.append(meal_name)
                    meal_entries[meal_name].append({
                        "name": f"{meal_name} ({int(calories)} cal)",
                        "quantity": 1.0,
                        "mfp_id": None,
                        "nutritional_info": nutrition,
                    })

        return [
            {"meal_name": mn, "entries": meal_entries[mn]}
            for mn in meal_order
        ]

    @staticmethod
    def _parse_diary_entry(de: dict) -> dict | None:
        """Extract a usable food entry from a diary_entry dict."""
        # Try nested food object first
        food = de.get("food", {})
        name = food.get("description") or food.get("name") or food.get("brand_name", "")
        mfp_id = food.get("id")

        # Fall back to top-level fields
        if not name:
            name = de.get("description") or de.get("name") or de.get("food_name", "")
        if not mfp_id:
            mfp_id = de.get("food_id") or de.get("id")

        if not name:
            return None

        nutrition = de.get("nutritional_contents", {})
        quantity = de.get("serving_quantity") or de.get("quantity") or 1.0

        return {
            "name": name,
            "quantity": quantity,
            "mfp_id": mfp_id,
            "nutritional_info": nutrition,
        }

    # --- Search (uses API) ---

    def search_food_sync(self, query: str) -> list[dict]:
        """Search MFP food database. Returns list with name, mfp_id, serving_sizes, nutrition, version."""
        data = self._api_get("v2/nutrition", [
            ("q", query),
            ("fields[]", "nutritional_contents"),
            ("fields[]", "name"),
            ("fields[]", "brand_name"),
            ("fields[]", "serving_sizes"),
        ])
        results = []
        for wrapper in data.get("items", []):
            inner = wrapper.get("item", wrapper)
            name = (
                inner.get("description", "")
                or inner.get("name", "")
                or inner.get("brand_name", "")
            )
            mfp_id = inner.get("id")
            if name:
                nc = inner.get("nutritional_contents", {})
                energy = nc.get("energy", {})
                results.append({
                    "name": name,
                    "mfp_id": mfp_id,
                    "serving_sizes": inner.get("serving_sizes", []),
                    "nutrition": {
                        "calories": energy.get("value", 0) if isinstance(energy, dict) else 0,
                        "protein": nc.get("protein", 0),
                        "carbs": nc.get("carbohydrates", 0),
                        "fat": nc.get("fat", 0),
                    },
                    "version": str(inner.get("version", mfp_id)),
                })
        return results

    def _lookup_food_sync(self, food_name: str, mfp_food_id: str) -> dict:
        """Fetch version and serving_sizes for a food via the search API.

        Returns {version, serving_sizes} or sensible defaults.
        """
        try:
            data = self._api_get("v2/nutrition", [
                ("q", food_name),
                ("fields[]", "serving_sizes"),
            ])
            for wrapper in data.get("items", []):
                inner = wrapper.get("item", {})
                if str(inner.get("id")) == str(mfp_food_id):
                    return {
                        "version": str(inner.get("version", mfp_food_id)),
                        "serving_sizes": inner.get("serving_sizes", []),
                    }
        except Exception:
            logger.debug("Food lookup failed for '%s', using defaults", food_name)
        return {"version": str(mfp_food_id), "serving_sizes": []}

    def get_food_details_sync(self, mfp_id: int, hint_name: str = "") -> dict | None:
        """Fetch food details. Uses hint_name to search, then matches by ID.

        The direct endpoint v2/nutrition/{id} returns 404, so we search
        by name and filter by ID.
        """
        query = hint_name or str(mfp_id)
        try:
            data = self._api_get("v2/nutrition", [
                ("q", query),
                ("fields[]", "serving_sizes"),
            ])
            for wrapper in data.get("items", []):
                inner = wrapper.get("item", {})
                if str(inner.get("id")) == str(mfp_id):
                    name = (
                        inner.get("description", "")
                        or inner.get("name", "")
                        or inner.get("brand_name", "")
                    )
                    return {"name": name, "mfp_id": mfp_id} if name else None
        except Exception:
            pass
        return None

    def add_entry_sync(
        self,
        date_str: str,
        meal_name: str,
        food_name: str,
        mfp_food_id: str,
        servings: float = 1.0,
        serving_size_index: int | None = None,
    ) -> bool:
        """Add a food entry to the MFP diary. Raises on failure."""
        if not mfp_food_id or mfp_food_id in ("None", ""):
            raise ValueError(f"No food ID for '{food_name}' — cannot sync to MFP")

        # Fetch version and valid serving_size from MFP
        info = self._lookup_food_sync(food_name, mfp_food_id)
        version = info["version"]
        serving_sizes = info["serving_sizes"]

        if not serving_sizes:
            raise ValueError(
                f"Could not find serving sizes for '{food_name}' (id={mfp_food_id}) — "
                "cannot build a valid MFP request"
            )

        ss = None
        if serving_size_index is not None:
            ss = next((s for s in serving_sizes if s.get("index") == serving_size_index), None)
        if ss is None:
            ss = serving_sizes[0]

        serving_size = {
            "value": ss.get("value", 1.0),
            "unit": ss.get("unit", "serving"),
            "nutrition_multiplier": ss.get("nutrition_multiplier", 1.0),
        }

        meal_position = _SLOT_TO_MEAL_POSITION.get(meal_name, 3)

        payload = {
            "items": [
                {
                    "type": "food_entry",
                    "date": date_str,
                    "meal_position": meal_position,
                    "food": {
                        "id": str(mfp_food_id),
                        "version": version,
                    },
                    "servings": servings,
                    "serving_size": serving_size,
                }
            ]
        }

        self._api_post("v2/diary", payload)
        logger.info("Added '%s' to MFP diary (%s, %s)", food_name, date_str, meal_name)
        return True

    # --- Async wrappers ---

    async def validate(self) -> str:
        return await asyncio.to_thread(self.validate_sync)

    async def get_day(self, target_date: date) -> list[dict]:
        return await asyncio.to_thread(self.get_day_sync, target_date)

    async def search_food(self, query: str) -> list[dict]:
        return await asyncio.to_thread(self.search_food_sync, query)

    async def get_food_details(self, mfp_id: int) -> dict | None:
        return await asyncio.to_thread(self.get_food_details_sync, mfp_id)

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str,
                        servings: float = 1.0, serving_size_index: int | None = None) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id,
                                       servings, serving_size_index)
