from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from urllib import parse

import cloudscraper
import lxml.html
import requests


class MfpClient:
    """MFP client with direct email/password login (no browser cookies needed)."""

    BASE_URL = "https://www.myfitnesspal.com/"
    CSRF_PATH = "api/auth/csrf"
    LOGIN_PATH = "api/auth/callback/credentials"
    AUTH_TOKEN_PATH = "user/auth_token?refresh=true"
    DIARY_PATH = "food/diary/{username}?date={date}"
    SEARCH_PATH = "food/search"
    ABBREVIATIONS = {"carbs": "carbohydrates"}

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self.session = cloudscraper.create_scraper(sess=requests.Session())
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        self._access_token: str | None = None
        self._user_id: str | None = None
        self._effective_username: str | None = None
        self._logged_in = False

    # --- Authentication ---

    def login_sync(self) -> None:
        """Authenticate with MFP using email/password."""
        if self._logged_in:
            return

        # Step 1: Get CSRF token
        csrf_url = parse.urljoin(self.BASE_URL, self.CSRF_PATH)
        csrf_resp = self.session.get(csrf_url)
        csrf_resp.raise_for_status()
        csrf_token = csrf_resp.json().get("csrfToken", "")

        # Step 2: Login with credentials
        login_url = parse.urljoin(self.BASE_URL, self.LOGIN_PATH)
        login_data = {
            "username": self._username,
            "password": self._password,
            "csrfToken": csrf_token,
            "callbackUrl": "/",
            "json": "true",
        }
        login_resp = self.session.post(login_url, data=login_data)
        login_resp.raise_for_status()

        login_result = login_resp.json()
        login_ok = login_result.get("url")
        if not login_ok or "error" in str(login_ok).lower():
            raise ValueError(f"MFP login failed for user {self._username}")

        # Step 3: Get auth token
        auth_url = parse.urljoin(self.BASE_URL, self.AUTH_TOKEN_PATH)
        auth_resp = self.session.get(auth_url)
        if not auth_resp.ok or not auth_resp.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("MFP login succeeded but could not get auth token. Check credentials.")

        auth_data = auth_resp.json()
        self._access_token = auth_data.get("access_token")
        self._user_id = auth_data.get("user_id")
        self._effective_username = self._username
        self._logged_in = True

        # Try to get the effective username from user metadata
        try:
            self._effective_username = self._get_effective_username()
        except Exception:
            pass

    def _get_effective_username(self) -> str:
        """Get the real username (may differ from login email)."""
        url = parse.urljoin(
            "https://api.myfitnesspal.com/",
            f"/v2/users/{self._user_id}?fields[]=account"
        )
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "mfp-client-id": "mfp-main-js",
            "mfp-user-id": self._user_id or "",
        }
        resp = self.session.get(url, headers=headers)
        if resp.ok:
            return resp.json()["item"]["username"]
        return self._username

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login_sync()

    # --- Read diary ---

    def get_day_sync(self, target_date: date) -> list[dict]:
        """Get all meals for a given date. Returns list of {meal_name, entries}."""
        self._ensure_logged_in()

        date_str = target_date.strftime("%Y-%m-%d")
        url = parse.urljoin(
            self.BASE_URL,
            f"food/diary/{self._effective_username}?date={date_str}"
        )
        content = self.session.get(url).content.decode("utf8")
        document = lxml.html.document_fromstring(content)

        return self._parse_meals(document)

    def _parse_meals(self, document) -> list[dict]:
        """Parse meal data from the diary HTML page."""
        meals = []
        fields = None
        meal_headers = document.xpath("//tr[@class='meal_header']")

        for meal_header in meal_headers:
            tds = meal_header.findall("td")
            meal_name = tds[0].text.strip() if tds[0].text else "Unknown"

            if fields is None:
                fields = ["name"]
                for td in tds[1:]:
                    name = (td.text or "").lower().strip()
                    fields.append(self.ABBREVIATIONS.get(name, name))

            this = meal_header
            entries = []

            while True:
                this = this.getnext()
                if this is None or this.attrib.get("class") is not None:
                    break
                columns = this.findall("td")
                if not columns:
                    break

                # Get food name
                anchor = columns[0].find("a")
                if anchor is not None and anchor.text:
                    name = anchor.text.strip()
                elif columns[0].text:
                    name = columns[0].text.strip()
                else:
                    continue

                # Get nutritional info
                nutrition = {}
                for n in range(1, len(columns)):
                    try:
                        nutr_name = fields[n]
                    except IndexError:
                        continue
                    text = columns[n].text_content().strip()
                    try:
                        value = float(re.sub(r"[^-\d.]+", "", text))
                    except (ValueError, TypeError):
                        value = 0
                    nutrition[nutr_name] = value

                entries.append({
                    "name": name,
                    "quantity": 1.0,
                    "mfp_id": None,
                    "nutritional_info": nutrition,
                })

            meals.append({"meal_name": meal_name, "entries": entries})

        return meals

    # --- Search ---

    def search_food_sync(self, query: str) -> list[dict]:
        """Search MFP food database."""
        self._ensure_logged_in()

        search_url = parse.urljoin(self.BASE_URL, self.SEARCH_PATH)
        params = {"search": query}
        content = self.session.get(search_url, params=params).content.decode("utf8")
        document = lxml.html.document_fromstring(content)

        results = []
        for item in document.xpath("//li[@class='matched-food']//a"):
            name = item.text_content().strip()
            href = item.get("href", "")
            # Try to extract food ID from href
            mfp_id = None
            match = re.search(r"/food/item/(\d+)", href)
            if match:
                mfp_id = int(match.group(1))
            if name:
                results.append({"name": name, "mfp_id": mfp_id})

        return results

    def get_food_details_sync(self, mfp_id: int) -> dict | None:
        """Get details for a specific food item."""
        self._ensure_logged_in()
        try:
            url = parse.urljoin(self.BASE_URL, f"food/item/{mfp_id}")
            content = self.session.get(url).content.decode("utf8")
            document = lxml.html.document_fromstring(content)
            title_el = document.xpath("//h1")
            if title_el:
                return {"name": title_el[0].text_content().strip(), "mfp_id": mfp_id}
        except Exception:
            pass
        return None

    def add_entry_sync(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        """Add a food entry to MFP diary. Placeholder — MFP write API is undocumented."""
        self._ensure_logged_in()
        # TODO: Implement when MFP write API is reverse-engineered
        return True

    # --- Async wrappers ---

    async def login(self) -> None:
        return await asyncio.to_thread(self.login_sync)

    async def get_day(self, target_date: date) -> list[dict]:
        return await asyncio.to_thread(self.get_day_sync, target_date)

    async def search_food(self, query: str) -> list[dict]:
        return await asyncio.to_thread(self.search_food_sync, query)

    async def get_food_details(self, mfp_id: int) -> dict | None:
        return await asyncio.to_thread(self.get_food_details_sync, mfp_id)

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id)
