import os

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ENCRYPTION_KEY: str = os.environ.get("ENCRYPTION_KEY", "")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable is required")

DB_PATH: str = os.environ.get("DB_PATH", "data/mfp_auto.db")
TURSO_DB_URL: str = os.environ.get("TURSO_DB_URL", "")
TURSO_AUTH_TOKEN: str = os.environ.get("TURSO_AUTH_TOKEN", "")

MEAL_SLOTS: list[str] = [
    "breakfast",
    "lunch",
    "dinner",
    "snacks",
]

MEAL_SLOT_LABELS: dict[str, str] = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snacks": "Snacks",
}

MEAL_SLOT_EMOJIS: dict[str, str] = {
    "breakfast": "\u2615",
    "lunch": "\U0001F35D",
    "dinner": "\U0001F37D",
    "snacks": "\U0001F95C",
}

# MFP meal names -> our slot mapping (1:1 now)
MFP_DEFAULT_MEALS: dict[str, str] = {
    "Breakfast": "breakfast",
    "Lunch": "lunch",
    "Dinner": "dinner",
    "Snacks": "snacks",
}

HIGH_CONFIDENCE_THRESHOLD: float = 0.70
DECAY_RATE: float = 0.95  # per-week decay factor
MAX_ALTERNATIVES: int = 3
SCRAPE_RATE_LIMIT: float = 1.0  # seconds between MFP requests
WEEK_TIMEOUT_MINUTES: int = 30
REMINDER_HOUR: int = 21  # 24h format, local time (Italy)
