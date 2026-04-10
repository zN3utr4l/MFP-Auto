import os

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ENCRYPTION_KEY: str = os.environ.get("ENCRYPTION_KEY", "")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable is required")

DB_PATH: str = os.environ.get("DB_PATH", "data/mfp_auto.db")

MEAL_SLOTS: list[str] = [
    "breakfast",
    "morning_snack",
    "lunch",
    "afternoon_snack",
    "pre_workout",
    "post_workout",
    "dinner",
]

MEAL_SLOT_LABELS: dict[str, str] = {
    "breakfast": "Breakfast",
    "morning_snack": "Morning Snack",
    "lunch": "Lunch",
    "afternoon_snack": "Afternoon Snack",
    "pre_workout": "Pre-Workout",
    "post_workout": "Post-Workout",
    "dinner": "Dinner",
}

MEAL_SLOT_EMOJIS: dict[str, str] = {
    "breakfast": "\u2615",
    "morning_snack": "\U0001F95C",
    "lunch": "\U0001F35D",
    "afternoon_snack": "\U0001F34E",
    "pre_workout": "\U0001F4AA",
    "post_workout": "\U0001F3CB\uFE0F",
    "dinner": "\U0001F37D",
}

# MFP default meal names -> our slot mapping (for 4-slot accounts)
MFP_DEFAULT_MEALS: dict[str, str] = {
    "Breakfast": "breakfast",
    "Lunch": "lunch",
    "Dinner": "dinner",
    "Snacks": "morning_snack",  # default fallback; refined during onboarding
}

HIGH_CONFIDENCE_THRESHOLD: float = 0.70
DECAY_RATE: float = 0.95  # per-week decay factor
MAX_ALTERNATIVES: int = 3
SCRAPE_RATE_LIMIT: float = 1.0  # seconds between MFP requests
WEEK_TIMEOUT_MINUTES: int = 30
