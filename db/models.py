from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    telegram_user_id: int
    mfp_username: str
    mfp_password_encrypted: str
    is_premium: bool = False
    onboarding_done: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MealEntry:
    telegram_user_id: int
    date: str  # YYYY-MM-DD
    day_of_week: int  # 0=Mon, 6=Sun
    slot: str
    food_name: str
    quantity: str
    mfp_food_id: str = ""
    serving_info: str = "{}"
    source: str = "bot_confirm"  # mfp_scrape | bot_confirm | bot_search
    synced_to_mfp: bool = False
    id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MealPattern:
    telegram_user_id: int
    slot: str
    day_type: str  # weekday | weekend | monday | tuesday | ...
    food_combo: str  # JSON array
    mfp_food_ids: str  # JSON array
    weight: float = 1.0
    last_confirmed: str = ""
    id: int | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    serving_info: str = "{}"

    def get_food_combo_list(self) -> list[str]:
        return json.loads(self.food_combo)

    def get_mfp_food_ids_list(self) -> list[str]:
        return json.loads(self.mfp_food_ids)


@dataclass
class WeekProgress:
    telegram_user_id: int
    week_start: str  # YYYY-MM-DD
    current_day: str  # YYYY-MM-DD
    status: str = "in_progress"  # in_progress | completed | stopped
    id: int | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
