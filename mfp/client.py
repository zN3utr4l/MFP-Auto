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
    "lunch": 1,
    "dinner": 2,
    "snacks": 3,
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
        Tries v2/diary/read_diary (individual food entries) first,
        falls back to v2/diary (meal-level summaries) on failure.
        """
        date_str = target_date.strftime("%Y-%m-%d")

        # Try the undocumented read_diary endpoint for individual food entries
        try:
            result = self._get_day_via_read_diary(date_str)
            logger.info("read_diary OK for %s: %d meals", date_str,  len(result))
            return result
        except Exception as e:
            logger.warning("read_diary failed for %s: %s — falling back to v2/diary", date_str, e)

        # Fallback: v2/diary (meal-level summaries only)
        return self._get_day_via_diary_summary(date_str)

    def _get_day_via_read_diary(self, date_str: str) -> list[dict]:
        """Fetch individual food entries via v2/diary/read_diary."""
        data = self._api_get("v2/diary/read_diary", [
            ("entry_date", date_str),
            ("types", "food_entry"),
        ])

        items = data.get("items", [])
        if not items:
            raise ValueError("No items from read_diary")

        # Group food_entry items by meal
        meal_entries: dict[str, list[dict]] = {}
        meal_order: list[str] = []

        for item in items:
            if item.get("type") != "food_entry":
                continue

            meal_name = item.get("meal_name") or item.get("diary_meal", "Unknown")
            if meal_name not in meal_entries:
                meal_entries[meal_name] = []
                meal_order.append(meal_name)

            food = item.get("food", {})
            name = food.get("description") or food.get("name") or food.get("brand_name", "")
            mfp_id = food.get("id")

            if not name:
                continue

            nc = item.get("nutritional_contents", {})
            ss = item.get("serving_size", {})
            servings = item.get("servings", 1.0)
            quantity = f"{servings} {ss.get('unit', 'serving')}" if ss.get("unit") else str(servings)

            meal_entries[meal_name].append({
                "name": name,
                "quantity": quantity,
                "mfp_id": mfp_id,
                "nutritional_info": nc,
                "serving_size": ss,
                "servings": servings,
            })

        if not any(meal_entries.values()):
            raise ValueError("read_diary returned items but no parseable food entries")

        logger.info("read_diary: %d entries across %d meals for %s",
                     sum(len(v) for v in meal_entries.values()), len(meal_order), date_str)

        return [
            {"meal_name": mn, "entries": meal_entries[mn]}
            for mn in meal_order
        ]

    def _get_day_via_diary_summary(self, date_str: str) -> list[dict]:
        """Fallback: fetch meal-level calorie summaries via v2/diary."""
        data = self._api_get("v2/diary", [
            ("entry_date", date_str),
            ("fields[]", "nutritional_contents"),
        ])

        meals = []
        for item in data.get("items", []):
            if item.get("type") != "diary_meal":
                continue
            meal_name = item.get("diary_meal", "Unknown")
            nutrition = item.get("nutritional_contents", {})
            energy = nutrition.get("energy", {})
            calories = energy.get("value", 0) if isinstance(energy, dict) else 0

            entries = []
            if calories > 0:
                entries.append({
                    "name": f"{meal_name} ({int(calories)} cal)",
                    "quantity": 1.0,
                    "mfp_id": None,
                    "nutritional_info": nutrition,
                    "summary_only": True,
                })
            meals.append({"meal_name": meal_name, "entries": entries})

        return meals

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

        Tries multiple search strategies:
        1. Full food name
        2. First significant word (for long brand+product names)
        3. Food ID as query

        Returns {version, serving_sizes} or sensible defaults.
        """
        queries = [food_name]
        # For long names like "Esselunga - Cozze Cilene", try shorter queries
        # Strip brand prefix (before " - ") and use core product name
        if " - " in food_name:
            parts = food_name.split(" - ")
            queries.append(parts[-1].strip())  # last part (product name)
            if len(parts) > 2:
                queries.append(parts[1].strip())  # middle part
        elif len(food_name.split()) > 3:
            queries.append(" ".join(food_name.split()[:3]))

        for query in queries:
            try:
                data = self._api_get("v2/nutrition", [
                    ("q", query),
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
                logger.debug("Food lookup with query '%s' failed", query)

        logger.warning("Food '%s' (id=%s) not found in any search query", food_name, mfp_food_id)
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
        fallback_serving: dict | None = None,
    ) -> bool:
        """Add a food entry to the MFP diary. Raises on failure.

        fallback_serving: optional dict with unit/nutrition_multiplier from
        a previously stored serving_info, used when MFP search can't find
        the food to look up serving_sizes.
        """
        if not mfp_food_id or mfp_food_id in ("None", ""):
            raise ValueError(f"No food ID for '{food_name}' — cannot sync to MFP")

        # Fetch version and valid serving_size from MFP
        info = self._lookup_food_sync(food_name, mfp_food_id)
        version = info["version"]
        serving_sizes = info["serving_sizes"]

        if serving_sizes:
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
        elif fallback_serving and fallback_serving.get("unit"):
            logger.info("Using stored serving_info fallback for '%s'", food_name)
            serving_size = {
                "value": fallback_serving.get("value", 1.0),
                "unit": fallback_serving["unit"],
                "nutrition_multiplier": fallback_serving.get("nutrition_multiplier", 1.0),
            }
        else:
            # Last resort: use default "1 serving" — MFP resolves nutrition from the food ID
            logger.warning("Using default serving for '%s' (id=%s) — lookup and fallback both empty",
                           food_name, mfp_food_id)
            serving_size = {"value": 1.0, "unit": "serving", "nutrition_multiplier": 1.0}

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

    async def get_food_details(self, mfp_id: int, hint_name: str = "") -> dict | None:
        return await asyncio.to_thread(self.get_food_details_sync, mfp_id, hint_name)

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str,
                        servings: float = 1.0, serving_size_index: int | None = None,
                        fallback_serving: dict | None = None) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id,
                                       servings, serving_size_index, fallback_serving)
