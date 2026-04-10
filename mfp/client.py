from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from urllib import parse

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)


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

    # --- Read diary ---

    def get_day_sync(self, target_date: date) -> list[dict]:
        """Get meals for a date. Returns list of {meal_name, entries, nutritional_contents}."""
        date_str = target_date.strftime("%Y-%m-%d")
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
            calories = nutrition.get("energy", {}).get("value", 0) if isinstance(nutrition.get("energy"), dict) else 0

            # The API returns meal totals, not individual food entries.
            # We create a single summary entry per meal for pattern matching.
            entries = []
            if calories > 0:
                entries.append({
                    "name": f"{meal_name} ({int(calories)} cal)",
                    "quantity": 1.0,
                    "mfp_id": None,
                    "nutritional_info": nutrition,
                })

            meals.append({
                "meal_name": meal_name,
                "entries": entries,
            })

        return meals

    # --- Search (uses API) ---

    def search_food_sync(self, query: str) -> list[dict]:
        """Search MFP food database."""
        data = self._api_get("v2/nutrition", [
            ("q", query),
            ("fields[]", "nutritional_contents"),
            ("fields[]", "name"),
            ("fields[]", "brand_name"),
        ])
        results = []
        for item in data.get("items", []):
            name = item.get("name", "") or item.get("brand_name", "")
            mfp_id = item.get("id")
            if name:
                results.append({"name": name, "mfp_id": mfp_id})
        return results

    def get_food_details_sync(self, mfp_id: int) -> dict | None:
        try:
            data = self._api_get(f"v2/nutrition/{mfp_id}", [
                ("fields[]", "name"),
                ("fields[]", "brand_name"),
            ])
            item = data.get("item", {})
            name = item.get("name", "") or item.get("brand_name", "")
            return {"name": name, "mfp_id": mfp_id} if name else None
        except Exception:
            return None

    def add_entry_sync(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        # TODO: Implement via MFP API
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

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id)
