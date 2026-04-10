from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from urllib import parse

import lxml.html
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)


class MfpClient:
    """MFP client with direct email/password login via curl_cffi (bypasses Cloudflare)."""

    BASE_URL = "https://www.myfitnesspal.com/"
    API_URL = "https://api.myfitnesspal.com/"
    CSRF_PATH = "api/auth/csrf"
    LOGIN_PATH = "api/auth/callback/credentials"
    AUTH_TOKEN_PATH = "user/auth_token?refresh=true"
    SEARCH_PATH = "food/search"
    ABBREVIATIONS = {"carbs": "carbohydrates"}

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self.session = curl_requests.Session(impersonate="chrome")
        self._access_token: str | None = None
        self._user_id: str | None = None
        self._effective_username: str | None = None
        self._logged_in = False

    # --- Authentication ---

    def login_sync(self) -> None:
        """Authenticate with MFP using email/password."""
        if self._logged_in:
            return

        # Step 1: Visit login page to establish session cookies
        login_page_url = parse.urljoin(self.BASE_URL, "account/login")
        warmup = self.session.get(login_page_url)
        logger.info("MFP warmup: status=%s", warmup.status_code)

        # Step 2: Get CSRF token
        csrf_url = parse.urljoin(self.BASE_URL, self.CSRF_PATH)
        csrf_resp = self.session.get(csrf_url)
        logger.info("MFP CSRF: status=%s type=%s",
                     csrf_resp.status_code, csrf_resp.headers.get("content-type", ""))
        try:
            csrf_token = csrf_resp.json().get("csrfToken", "")
        except Exception:
            raise ValueError(
                f"Could not parse CSRF response from MFP "
                f"(status {csrf_resp.status_code}, body: {csrf_resp.text[:300]})"
            )
        if not csrf_token:
            raise ValueError("MFP returned empty CSRF token")

        # Step 3: Login with credentials
        login_url = parse.urljoin(self.BASE_URL, self.LOGIN_PATH)
        login_data = {
            "username": self._username,
            "password": self._password,
            "csrfToken": csrf_token,
            "callbackUrl": "/",
            "json": "true",
        }
        login_resp = self.session.post(login_url, data=login_data)
        logger.info("MFP login: status=%s", login_resp.status_code)

        try:
            login_result = login_resp.json()
        except Exception:
            raise ValueError(
                f"MFP login returned non-JSON "
                f"(status {login_resp.status_code}, body: {login_resp.text[:300]})"
            )

        login_ok = login_result.get("url")
        if not login_ok or "error" in str(login_ok).lower():
            raise ValueError(f"MFP login failed for {self._username}: {login_result}")

        # Step 4: Get auth token
        auth_url = parse.urljoin(self.BASE_URL, self.AUTH_TOKEN_PATH)
        auth_resp = self.session.get(auth_url)
        if not auth_resp.headers.get("content-type", "").startswith("application/json"):
            raise ValueError(
                f"Could not get MFP auth token "
                f"(status {auth_resp.status_code}, body: {auth_resp.text[:300]})"
            )

        auth_data = auth_resp.json()
        self._access_token = auth_data.get("access_token")
        self._user_id = auth_data.get("user_id")
        self._effective_username = self._username
        self._logged_in = True
        logger.info("MFP logged in as user_id=%s", self._user_id)

        # Try to resolve the effective username (email -> actual username)
        try:
            self._effective_username = self._get_effective_username()
            logger.info("MFP effective username: %s", self._effective_username)
        except Exception:
            pass

    def _get_effective_username(self) -> str:
        url = parse.urljoin(self.API_URL, f"/v2/users/{self._user_id}?fields[]=account")
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
        self._ensure_logged_in()
        date_str = target_date.strftime("%Y-%m-%d")
        url = parse.urljoin(self.BASE_URL, f"food/diary/{self._effective_username}?date={date_str}")
        content = self.session.get(url).content.decode("utf8")
        document = lxml.html.document_fromstring(content)
        return self._parse_meals(document)

    def _parse_meals(self, document) -> list[dict]:
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

                anchor = columns[0].find("a")
                if anchor is not None and anchor.text:
                    name = anchor.text.strip()
                elif columns[0].text:
                    name = columns[0].text.strip()
                else:
                    continue

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
        self._ensure_logged_in()
        search_url = parse.urljoin(self.BASE_URL, self.SEARCH_PATH)
        content = self.session.get(search_url, params={"search": query}).content.decode("utf8")
        document = lxml.html.document_fromstring(content)

        results = []
        for item in document.xpath("//li[@class='matched-food']//a"):
            name = item.text_content().strip()
            href = item.get("href", "")
            mfp_id = None
            match = re.search(r"/food/item/(\d+)", href)
            if match:
                mfp_id = int(match.group(1))
            if name:
                results.append({"name": name, "mfp_id": mfp_id})
        return results

    def get_food_details_sync(self, mfp_id: int) -> dict | None:
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
