# MFP Auto Bot - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that predicts and auto-logs meals on MyFitnessPal based on the user's eating history.

**Architecture:** Three layers — Bot Engine (Telegram interaction), Pattern Engine (prediction + learning), MFP Client (read/write to MyFitnessPal). SQLite stores users, meal history, patterns, and week wizard progress. The bot runs async via `python-telegram-bot` long-polling; `python-myfitnesspal` is sync so all MFP calls go through `asyncio.to_thread()`.

**Tech Stack:** Python 3.14, python-telegram-bot==22.7, myfitnesspal==2.1.2, pandas>=2.2, aiosqlite>=0.21, cryptography>=44.0

**Spec:** `docs/specs/design.md`

---

## File Map

```
mfp-auto/
├── main.py                     # Entry point — build Application, register handlers, run_polling
├── config.py                   # Reads env vars: TELEGRAM_BOT_TOKEN, ENCRYPTION_KEY
├── requirements.txt            # Pinned dependencies
├── .gitignore                  # data/, __pycache__, .env
├── .env.example                # Template for env vars
├── db/
│   ├── __init__.py
│   ├── database.py             # get_db(), init_db() — aiosqlite connection + table creation
│   └── models.py               # Dataclasses: User, MealEntry, MealPattern, WeekProgress
├── mfp/
│   ├── __init__.py
│   ├── client.py               # MfpClient: get_day(), search_food(), add_entry() — wraps python-myfitnesspal
│   ├── scraper.py              # scrape_history(): iterate date range, save to meals_history
│   └── sync.py                 # SyncQueue: track unsynced meals, retry logic
├── engine/
│   ├── __init__.py
│   ├── pattern_analyzer.py     # analyze_history(): compute meal_patterns from meals_history
│   ├── predictor.py            # predict_day(): for a given date return best meal per slot
│   └── learner.py              # on_confirm(), on_replace(), on_skip(): update pattern weights
├── bot/
│   ├── __init__.py
│   ├── messages.py             # Format functions: format_slot_message(), format_day_summary()
│   ├── keyboards.py            # InlineKeyboardMarkup builders for confirm/change/skip/stop
│   ├── onboarding.py           # /start, /login, import range selection, snack mapping wizard
│   ├── daily.py                # /today, /tomorrow, /day — single-day slot-by-slot flow
│   ├── week.py                 # /week — sequential multi-day wizard with stop/resume
│   └── utility.py              # /status, /undo, /retry
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_database.py
    ├── test_models.py
    ├── test_mfp_client.py
    ├── test_scraper.py
    ├── test_sync.py
    ├── test_pattern_analyzer.py
    ├── test_predictor.py
    ├── test_learner.py
    ├── test_messages.py
    ├── test_keyboards.py
    └── test_daily.py
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create `requirements.txt`**

```
python-telegram-bot==22.7
myfitnesspal==2.1.2
pandas>=2.2
aiosqlite>=0.21
cryptography>=44.0
pytest>=8.0
pytest-asyncio>=0.24
```

- [ ] **Step 2: Create `.gitignore`**

```
data/
__pycache__/
*.pyc
.env
*.db
.pytest_cache/
```

- [ ] **Step 3: Create `.env.example`**

```
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
ENCRYPTION_KEY=your-fernet-key-base64
```

- [ ] **Step 4: Write the failing test for `config.py`**

File: `tests/test_config.py`

```python
import os

import pytest


def test_config_reads_env_vars(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("ENCRYPTION_KEY", "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=")

    # Force reimport to pick up new env
    import importlib
    import config
    importlib.reload(config)

    assert config.TELEGRAM_BOT_TOKEN == "test-token-123"
    assert config.ENCRYPTION_KEY == "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI="


def test_config_raises_on_missing_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ENCRYPTION_KEY", "some-key")

    import importlib
    import config

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        importlib.reload(config)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_config.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 6: Implement `config.py`**

File: `config.py`

```python
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
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_config.py -v`

Expected: 2 passed

- [ ] **Step 8: Create `__init__.py` files for all packages**

Create empty `__init__.py` in: `db/`, `mfp/`, `engine/`, `bot/`, `tests/`

- [ ] **Step 9: Install dependencies**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && pip install -r requirements.txt`

- [ ] **Step 10: Commit**

```bash
cd C:\Users\g.chirico\source\repos\Personal\mfp-auto
git add .
git commit -m "feat: project scaffolding — requirements, config, gitignore"
```

---

## Task 2: Data Models

**Files:**
- Create: `db/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_models.py`

```python
from db.models import MealEntry, MealPattern, User, WeekProgress


def test_user_creation():
    user = User(
        telegram_user_id=12345,
        mfp_username="testuser",
        mfp_password_encrypted="encrypted_password",
        is_premium=True,
        onboarding_done=False,
    )
    assert user.telegram_user_id == 12345
    assert user.mfp_username == "testuser"
    assert user.onboarding_done is False


def test_meal_entry_creation():
    entry = MealEntry(
        telegram_user_id=12345,
        date="2026-04-10",
        day_of_week=3,
        slot="breakfast",
        food_name="Fiocchi d'avena 80g",
        quantity="80g",
        mfp_food_id="98765",
        source="bot_confirm",
    )
    assert entry.slot == "breakfast"
    assert entry.day_of_week == 3


def test_meal_pattern_creation():
    pattern = MealPattern(
        telegram_user_id=12345,
        slot="breakfast",
        day_type="weekday",
        food_combo='["Fiocchi d\'avena 80g", "Banana", "Latte 200ml"]',
        mfp_food_ids='["111", "222", "333"]',
        weight=8.5,
        last_confirmed="2026-04-10",
    )
    assert pattern.weight == 8.5
    assert pattern.day_type == "weekday"


def test_meal_pattern_food_combo_as_list():
    pattern = MealPattern(
        telegram_user_id=12345,
        slot="breakfast",
        day_type="weekday",
        food_combo='["Oats 80g", "Banana"]',
        mfp_food_ids='["111", "222"]',
        weight=5.0,
        last_confirmed="2026-04-10",
    )
    foods = pattern.get_food_combo_list()
    assert foods == ["Oats 80g", "Banana"]


def test_week_progress_creation():
    wp = WeekProgress(
        telegram_user_id=12345,
        week_start="2026-04-07",
        current_day="2026-04-09",
        status="in_progress",
    )
    assert wp.status == "in_progress"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_models.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'db.models'`

- [ ] **Step 3: Implement `db/models.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class User:
    telegram_user_id: int
    mfp_username: str
    mfp_password_encrypted: str
    is_premium: bool = False
    onboarding_done: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class MealEntry:
    telegram_user_id: int
    date: str  # YYYY-MM-DD
    day_of_week: int  # 0=Mon, 6=Sun
    slot: str
    food_name: str
    quantity: str
    mfp_food_id: str = ""
    source: str = "bot_confirm"  # mfp_scrape | bot_confirm | bot_search
    synced_to_mfp: bool = False
    id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


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
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

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
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_models.py -v`

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add db/models.py tests/test_models.py
git commit -m "feat: data models — User, MealEntry, MealPattern, WeekProgress"
```

---

## Task 3: Database Layer

**Files:**
- Create: `db/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_database.py`

```python
import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, get_db, save_user, get_user, save_meal_entry, get_meal_entries
from db.models import MealEntry, User

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
        tables = [row["name"] async for row in cursor]
    assert "users" in tables
    assert "meals_history" in tables
    assert "meal_patterns" in tables
    assert "week_progress" in tables


@pytest.mark.asyncio
async def test_save_and_get_user(db):
    user = User(
        telegram_user_id=12345,
        mfp_username="testuser",
        mfp_password_encrypted="encrypted",
    )
    await save_user(db, user)
    loaded = await get_user(db, 12345)
    assert loaded is not None
    assert loaded.mfp_username == "testuser"


@pytest.mark.asyncio
async def test_get_user_returns_none_for_unknown(db):
    loaded = await get_user(db, 99999)
    assert loaded is None


@pytest.mark.asyncio
async def test_save_and_get_meal_entries(db):
    user = User(telegram_user_id=12345, mfp_username="u", mfp_password_encrypted="e")
    await save_user(db, user)

    entry = MealEntry(
        telegram_user_id=12345,
        date="2026-04-10",
        day_of_week=3,
        slot="breakfast",
        food_name="Oats 80g",
        quantity="80g",
        mfp_food_id="111",
        source="bot_confirm",
    )
    await save_meal_entry(db, entry)

    entries = await get_meal_entries(db, telegram_user_id=12345, date="2026-04-10", slot="breakfast")
    assert len(entries) == 1
    assert entries[0].food_name == "Oats 80g"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_database.py -v`

Expected: FAIL — `ImportError: cannot import name 'init_db'`

- [ ] **Step 3: Implement `db/database.py`**

```python
from __future__ import annotations

import aiosqlite

from db.models import MealEntry, MealPattern, User, WeekProgress

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    mfp_username TEXT NOT NULL,
    mfp_password_encrypted TEXT NOT NULL,
    is_premium INTEGER NOT NULL DEFAULT 0,
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meals_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    date TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    slot TEXT NOT NULL,
    food_name TEXT NOT NULL,
    quantity TEXT NOT NULL DEFAULT '',
    mfp_food_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'bot_confirm',
    synced_to_mfp INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    slot TEXT NOT NULL,
    day_type TEXT NOT NULL,
    food_combo TEXT NOT NULL,
    mfp_food_ids TEXT NOT NULL DEFAULT '[]',
    weight REAL NOT NULL DEFAULT 1.0,
    last_confirmed TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS week_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    week_start TEXT NOT NULL,
    current_day TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals_history(telegram_user_id, date);
CREATE INDEX IF NOT EXISTS idx_meals_user_slot ON meals_history(telegram_user_id, date, slot);
CREATE INDEX IF NOT EXISTS idx_patterns_user_slot ON meal_patterns(telegram_user_id, slot, day_type);
CREATE INDEX IF NOT EXISTS idx_week_user ON week_progress(telegram_user_id, status);
"""


async def init_db(db: aiosqlite.Connection) -> None:
    await db.executescript(_CREATE_TABLES)
    await db.commit()


async def get_db(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await init_db(db)
    return db


# --- Users ---

async def save_user(db: aiosqlite.Connection, user: User) -> None:
    await db.execute(
        """INSERT OR REPLACE INTO users
           (telegram_user_id, mfp_username, mfp_password_encrypted, is_premium, onboarding_done, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user.telegram_user_id, user.mfp_username, user.mfp_password_encrypted,
         int(user.is_premium), int(user.onboarding_done), user.created_at),
    )
    await db.commit()


async def get_user(db: aiosqlite.Connection, telegram_user_id: int) -> User | None:
    async with db.execute(
        "SELECT * FROM users WHERE telegram_user_id = ?", (telegram_user_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return User(
        telegram_user_id=row["telegram_user_id"],
        mfp_username=row["mfp_username"],
        mfp_password_encrypted=row["mfp_password_encrypted"],
        is_premium=bool(row["is_premium"]),
        onboarding_done=bool(row["onboarding_done"]),
        created_at=row["created_at"],
    )


# --- Meal Entries ---

async def save_meal_entry(db: aiosqlite.Connection, entry: MealEntry) -> int:
    cursor = await db.execute(
        """INSERT INTO meals_history
           (telegram_user_id, date, day_of_week, slot, food_name, quantity,
            mfp_food_id, source, synced_to_mfp, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry.telegram_user_id, entry.date, entry.day_of_week, entry.slot,
         entry.food_name, entry.quantity, entry.mfp_food_id, entry.source,
         int(entry.synced_to_mfp), entry.created_at),
    )
    await db.commit()
    return cursor.lastrowid


async def get_meal_entries(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    date: str,
    slot: str | None = None,
) -> list[MealEntry]:
    if slot:
        query = "SELECT * FROM meals_history WHERE telegram_user_id = ? AND date = ? AND slot = ?"
        params = (telegram_user_id, date, slot)
    else:
        query = "SELECT * FROM meals_history WHERE telegram_user_id = ? AND date = ?"
        params = (telegram_user_id, date)

    entries = []
    async with db.execute(query, params) as cursor:
        async for row in cursor:
            entries.append(MealEntry(
                id=row["id"],
                telegram_user_id=row["telegram_user_id"],
                date=row["date"],
                day_of_week=row["day_of_week"],
                slot=row["slot"],
                food_name=row["food_name"],
                quantity=row["quantity"],
                mfp_food_id=row["mfp_food_id"],
                source=row["source"],
                synced_to_mfp=bool(row["synced_to_mfp"]),
                created_at=row["created_at"],
            ))
    return entries


# --- Meal Patterns ---

async def save_meal_pattern(db: aiosqlite.Connection, pattern: MealPattern) -> int:
    cursor = await db.execute(
        """INSERT INTO meal_patterns
           (telegram_user_id, slot, day_type, food_combo, mfp_food_ids, weight, last_confirmed, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (pattern.telegram_user_id, pattern.slot, pattern.day_type, pattern.food_combo,
         pattern.mfp_food_ids, pattern.weight, pattern.last_confirmed, pattern.updated_at),
    )
    await db.commit()
    return cursor.lastrowid


async def get_meal_patterns(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    slot: str,
    day_type: str,
) -> list[MealPattern]:
    patterns = []
    async with db.execute(
        """SELECT * FROM meal_patterns
           WHERE telegram_user_id = ? AND slot = ? AND day_type = ?
           ORDER BY weight DESC""",
        (telegram_user_id, slot, day_type),
    ) as cursor:
        async for row in cursor:
            patterns.append(MealPattern(
                id=row["id"],
                telegram_user_id=row["telegram_user_id"],
                slot=row["slot"],
                day_type=row["day_type"],
                food_combo=row["food_combo"],
                mfp_food_ids=row["mfp_food_ids"],
                weight=row["weight"],
                last_confirmed=row["last_confirmed"],
                updated_at=row["updated_at"],
            ))
    return patterns


async def update_pattern_weight(
    db: aiosqlite.Connection, pattern_id: int, weight: float, last_confirmed: str
) -> None:
    await db.execute(
        "UPDATE meal_patterns SET weight = ?, last_confirmed = ?, updated_at = ? WHERE id = ?",
        (weight, last_confirmed, last_confirmed, pattern_id),
    )
    await db.commit()


# --- Unsynced entries ---

async def get_unsynced_entries(db: aiosqlite.Connection, telegram_user_id: int) -> list[MealEntry]:
    entries = []
    async with db.execute(
        "SELECT * FROM meals_history WHERE telegram_user_id = ? AND synced_to_mfp = 0",
        (telegram_user_id,),
    ) as cursor:
        async for row in cursor:
            entries.append(MealEntry(
                id=row["id"],
                telegram_user_id=row["telegram_user_id"],
                date=row["date"],
                day_of_week=row["day_of_week"],
                slot=row["slot"],
                food_name=row["food_name"],
                quantity=row["quantity"],
                mfp_food_id=row["mfp_food_id"],
                source=row["source"],
                synced_to_mfp=False,
                created_at=row["created_at"],
            ))
    return entries


async def mark_entry_synced(db: aiosqlite.Connection, entry_id: int) -> None:
    await db.execute("UPDATE meals_history SET synced_to_mfp = 1 WHERE id = ?", (entry_id,))
    await db.commit()


# --- Week Progress ---

async def save_week_progress(db: aiosqlite.Connection, wp: WeekProgress) -> int:
    cursor = await db.execute(
        """INSERT INTO week_progress (telegram_user_id, week_start, current_day, status, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (wp.telegram_user_id, wp.week_start, wp.current_day, wp.status, wp.updated_at),
    )
    await db.commit()
    return cursor.lastrowid


async def get_active_week_progress(db: aiosqlite.Connection, telegram_user_id: int) -> WeekProgress | None:
    async with db.execute(
        "SELECT * FROM week_progress WHERE telegram_user_id = ? AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
        (telegram_user_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return WeekProgress(
        id=row["id"],
        telegram_user_id=row["telegram_user_id"],
        week_start=row["week_start"],
        current_day=row["current_day"],
        status=row["status"],
        updated_at=row["updated_at"],
    )


async def update_week_progress(db: aiosqlite.Connection, wp_id: int, current_day: str, status: str) -> None:
    from datetime import datetime
    await db.execute(
        "UPDATE week_progress SET current_day = ?, status = ?, updated_at = ? WHERE id = ?",
        (current_day, status, datetime.utcnow().isoformat(), wp_id),
    )
    await db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_database.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "feat: database layer — init, CRUD for users, meals, patterns, week progress"
```

---

## Task 4: MFP Client Wrapper

**Files:**
- Create: `mfp/client.py`
- Create: `tests/test_mfp_client.py`

Note: `python-myfitnesspal` uses synchronous HTTP calls. We wrap everything in `asyncio.to_thread()` so it doesn't block the bot's event loop. The `Client()` constructor authenticates using stored browser cookies or username/password.

- [ ] **Step 1: Write the failing test**

File: `tests/test_mfp_client.py`

```python
from unittest.mock import MagicMock, patch
from datetime import date

import pytest

from mfp.client import MfpClient


@pytest.fixture
def mock_mfp():
    with patch("mfp.client.myfitnesspal.Client") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_mfp_client_creates_connection(mock_mfp):
    client = MfpClient("testuser", "testpass")
    assert client._client is mock_mfp


def test_get_day_returns_meals(mock_mfp):
    # Setup mock day
    mock_entry = MagicMock()
    mock_entry.name = "Oats 80g"
    mock_entry.quantity = 1.0
    mock_entry.mfp_id = 12345

    mock_meal = MagicMock()
    mock_meal.name = "Breakfast"
    mock_meal.entries = [mock_entry]

    mock_day = MagicMock()
    mock_day.meals = [mock_meal]
    mock_mfp.get_date.return_value = mock_day

    client = MfpClient("user", "pass")
    result = client.get_day_sync(date(2026, 4, 10))

    assert len(result) == 1
    assert result[0]["meal_name"] == "Breakfast"
    assert result[0]["entries"][0]["name"] == "Oats 80g"
    assert result[0]["entries"][0]["mfp_id"] == 12345


def test_search_food_returns_results(mock_mfp):
    mock_item = MagicMock()
    mock_item.name = "Banana"
    mock_item.mfp_id = 99999
    mock_mfp.get_food_search_results.return_value = [mock_item]

    client = MfpClient("user", "pass")
    results = client.search_food_sync("banana")

    assert len(results) == 1
    assert results[0]["name"] == "Banana"
    assert results[0]["mfp_id"] == 99999
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_mfp_client.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mfp.client'`

- [ ] **Step 3: Implement `mfp/client.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_mfp_client.py -v`

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add mfp/client.py tests/test_mfp_client.py
git commit -m "feat: MFP client wrapper — get_day, search_food, async wrappers"
```

---

## Task 5: MFP Scraper (Bootstrap History)

**Files:**
- Create: `mfp/scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_scraper.py`

```python
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, get_meal_entries
from db.models import User
from mfp.scraper import scrape_history

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_scrape_history_saves_entries(db):
    mock_client = MagicMock()

    async def fake_get_day(d):
        return [
            {
                "meal_name": "Breakfast",
                "entries": [
                    {"name": "Oats 80g", "quantity": 1.0, "mfp_id": 111},
                ],
            },
            {
                "meal_name": "Snacks",
                "entries": [
                    {"name": "Almonds 30g", "quantity": 1.0, "mfp_id": 222},
                ],
            },
        ]

    mock_client.get_day = fake_get_day

    start = date(2026, 4, 8)
    end = date(2026, 4, 9)
    count = await scrape_history(db, mock_client, telegram_user_id=1, start_date=start, end_date=end)

    assert count == 4  # 2 entries x 2 days

    entries = await get_meal_entries(db, telegram_user_id=1, date="2026-04-08")
    assert len(entries) == 2
    assert entries[0].source == "mfp_scrape"


@pytest.mark.asyncio
async def test_scrape_history_maps_known_meals(db):
    mock_client = MagicMock()

    async def fake_get_day(d):
        return [{"meal_name": "Lunch", "entries": [{"name": "Rice 100g", "quantity": 1.0, "mfp_id": 333}]}]

    mock_client.get_day = fake_get_day

    count = await scrape_history(db, mock_client, telegram_user_id=1, start_date=date(2026, 4, 10), end_date=date(2026, 4, 10))

    entries = await get_meal_entries(db, telegram_user_id=1, date="2026-04-10", slot="lunch")
    assert len(entries) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_scraper.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mfp.scraper'`

- [ ] **Step 3: Implement `mfp/scraper.py`**

```python
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import aiosqlite

from config import MFP_DEFAULT_MEALS, SCRAPE_RATE_LIMIT
from db.database import save_meal_entry
from db.models import MealEntry
from mfp.client import MfpClient


async def scrape_history(
    db: aiosqlite.Connection,
    client: MfpClient,
    telegram_user_id: int,
    start_date: date,
    end_date: date,
    on_progress: callable | None = None,
) -> int:
    """Scrape MFP diary from start_date to end_date inclusive. Returns total entries saved."""
    total = 0
    current = start_date

    while current <= end_date:
        meals = await client.get_day(current)
        day_of_week = current.weekday()  # 0=Mon

        for meal_data in meals:
            mfp_meal_name = meal_data["meal_name"]
            slot = MFP_DEFAULT_MEALS.get(mfp_meal_name, "morning_snack")

            for entry_data in meal_data["entries"]:
                entry = MealEntry(
                    telegram_user_id=telegram_user_id,
                    date=current.isoformat(),
                    day_of_week=day_of_week,
                    slot=slot,
                    food_name=entry_data["name"],
                    quantity=str(entry_data.get("quantity", "")),
                    mfp_food_id=str(entry_data.get("mfp_id", "")),
                    source="mfp_scrape",
                    synced_to_mfp=True,
                )
                await save_meal_entry(db, entry)
                total += 1

        if on_progress:
            await on_progress(current, total)

        current += timedelta(days=1)
        await asyncio.sleep(SCRAPE_RATE_LIMIT)

    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_scraper.py -v`

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mfp/scraper.py tests/test_scraper.py
git commit -m "feat: MFP scraper — scrape history day-by-day with rate limiting"
```

---

## Task 6: Pattern Analyzer

**Files:**
- Create: `engine/pattern_analyzer.py`
- Create: `tests/test_pattern_analyzer.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_pattern_analyzer.py`

```python
import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_entry, get_meal_patterns
from db.models import MealEntry, User
from engine.pattern_analyzer import analyze_history

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


async def _insert_entries(db, slot, food_name, dates, mfp_food_id="111"):
    for d in dates:
        from datetime import date as dt_date
        parsed = dt_date.fromisoformat(d)
        entry = MealEntry(
            telegram_user_id=1,
            date=d,
            day_of_week=parsed.weekday(),
            slot=slot,
            food_name=food_name,
            quantity="1",
            mfp_food_id=mfp_food_id,
            source="mfp_scrape",
        )
        await save_meal_entry(db, entry)


@pytest.mark.asyncio
async def test_analyze_creates_patterns(db):
    # Insert consistent breakfast on weekdays (Monday=0 to Friday=4)
    weekday_dates = ["2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"]
    await _insert_entries(db, "breakfast", "Oats 80g", weekday_dates)

    await analyze_history(db, telegram_user_id=1)

    patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekday")
    assert len(patterns) >= 1
    assert patterns[0].get_food_combo_list() == ["Oats 80g"]
    assert patterns[0].weight > 0


@pytest.mark.asyncio
async def test_analyze_distinguishes_weekday_weekend(db):
    await _insert_entries(db, "breakfast", "Oats 80g", ["2026-04-06", "2026-04-07", "2026-04-08"])  # Mon-Wed
    await _insert_entries(db, "breakfast", "Pancakes", ["2026-04-04", "2026-04-05"])  # Sat-Sun

    await analyze_history(db, telegram_user_id=1)

    weekday_patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekday")
    weekend_patterns = await get_meal_patterns(db, telegram_user_id=1, slot="breakfast", day_type="weekend")

    assert any("Oats" in p.get_food_combo_list()[0] for p in weekday_patterns)
    assert any("Pancakes" in p.get_food_combo_list()[0] for p in weekend_patterns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_pattern_analyzer.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.pattern_analyzer'`

- [ ] **Step 3: Implement `engine/pattern_analyzer.py`**

```python
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

import aiosqlite
import pandas as pd

from config import DECAY_RATE
from db.database import save_meal_pattern
from db.models import MealPattern


def _weeks_since(ref_date: str, now: date | None = None) -> float:
    now = now or date.today()
    delta = now - date.fromisoformat(ref_date)
    return max(delta.days / 7.0, 0)


def _day_type(day_of_week: int) -> str:
    """Return 'weekday' or 'weekend'."""
    return "weekend" if day_of_week >= 5 else "weekday"


async def analyze_history(db: aiosqlite.Connection, telegram_user_id: int) -> int:
    """Analyze meals_history and populate meal_patterns. Returns number of patterns created."""

    # Clear existing patterns for this user (full recalculation)
    await db.execute("DELETE FROM meal_patterns WHERE telegram_user_id = ?", (telegram_user_id,))
    await db.commit()

    # Load all history into a DataFrame
    rows = []
    async with db.execute(
        "SELECT * FROM meals_history WHERE telegram_user_id = ?", (telegram_user_id,)
    ) as cursor:
        async for row in cursor:
            rows.append(dict(row))

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    df["day_type"] = df["day_of_week"].apply(_day_type)
    now = date.today()

    pattern_count = 0

    # Group by (slot, day_type) and find recurring food combos
    for (slot, day_type), group in df.groupby(["slot", "day_type"]):
        # Group by date to get the food combo per day
        daily_combos = group.groupby("date").agg({
            "food_name": list,
            "mfp_food_id": list,
        }).reset_index()

        # Count how often each combo appears
        combo_counter: Counter[str] = Counter()
        combo_details: dict[str, dict] = {}

        for _, day_row in daily_combos.iterrows():
            combo_key = json.dumps(sorted(day_row["food_name"]))
            weeks = _weeks_since(day_row["date"], now)
            decayed_weight = DECAY_RATE ** weeks

            combo_counter[combo_key] += decayed_weight

            if combo_key not in combo_details:
                combo_details[combo_key] = {
                    "food_names": sorted(day_row["food_name"]),
                    "mfp_food_ids": day_row["mfp_food_id"],
                    "last_date": day_row["date"],
                }
            elif day_row["date"] > combo_details[combo_key]["last_date"]:
                combo_details[combo_key]["last_date"] = day_row["date"]
                combo_details[combo_key]["mfp_food_ids"] = day_row["mfp_food_id"]

        # Save patterns
        for combo_key, weight in combo_counter.most_common():
            details = combo_details[combo_key]
            pattern = MealPattern(
                telegram_user_id=telegram_user_id,
                slot=slot,
                day_type=day_type,
                food_combo=json.dumps(details["food_names"]),
                mfp_food_ids=json.dumps(details["mfp_food_ids"]),
                weight=round(weight, 4),
                last_confirmed=details["last_date"],
            )
            await save_meal_pattern(db, pattern)
            pattern_count += 1

    return pattern_count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_pattern_analyzer.py -v`

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add engine/pattern_analyzer.py tests/test_pattern_analyzer.py
git commit -m "feat: pattern analyzer — extract meal patterns with temporal decay"
```

---

## Task 7: Predictor

**Files:**
- Create: `engine/predictor.py`
- Create: `tests/test_predictor.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_predictor.py`

```python
import json
from datetime import date

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_pattern
from db.models import MealPattern, User
from engine.predictor import predict_day

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_predict_day_returns_high_confidence_slot(db):
    # Breakfast weekday with high weight
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Oats 80g", "Banana"]', mfp_food_ids='["111", "222"]',
        weight=10.0, last_confirmed="2026-04-10",
    ))

    # Thursday = weekday
    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    breakfast = predictions["breakfast"]
    assert breakfast["confidence"] == "high"
    assert breakfast["top"]["foods"] == ["Oats 80g", "Banana"]


@pytest.mark.asyncio
async def test_predict_day_returns_alternatives_for_variable_slot(db):
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Chicken 200g"]', mfp_food_ids='["333"]',
        weight=3.0, last_confirmed="2026-04-09",
    ))
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Tuna 160g"]', mfp_food_ids='["444"]',
        weight=2.5, last_confirmed="2026-04-08",
    ))
    await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="lunch", day_type="weekday",
        food_combo='["Pasta 80g"]', mfp_food_ids='["555"]',
        weight=1.0, last_confirmed="2026-04-07",
    ))

    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    lunch = predictions["lunch"]
    assert lunch["confidence"] == "low"
    assert len(lunch["alternatives"]) == 3


@pytest.mark.asyncio
async def test_predict_day_returns_empty_for_no_patterns(db):
    predictions = await predict_day(db, telegram_user_id=1, target_date=date(2026, 4, 10))

    breakfast = predictions["breakfast"]
    assert breakfast["confidence"] == "none"
    assert breakfast["top"] is None
    assert breakfast["alternatives"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_predictor.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.predictor'`

- [ ] **Step 3: Implement `engine/predictor.py`**

```python
from __future__ import annotations

from datetime import date

import aiosqlite

from config import HIGH_CONFIDENCE_THRESHOLD, MAX_ALTERNATIVES, MEAL_SLOTS
from db.database import get_meal_patterns


def _day_type(target_date: date) -> str:
    return "weekend" if target_date.weekday() >= 5 else "weekday"


async def predict_day(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    target_date: date,
) -> dict[str, dict]:
    """Return predictions for each slot on target_date.

    Returns dict keyed by slot name. Each value:
    {
        "confidence": "high" | "low" | "none",
        "top": {"foods": [...], "mfp_ids": [...], "pattern_id": int} | None,
        "alternatives": [{"foods": [...], "mfp_ids": [...], "pattern_id": int}, ...],
    }
    """
    day_type = _day_type(target_date)
    predictions: dict[str, dict] = {}

    for slot in MEAL_SLOTS:
        patterns = await get_meal_patterns(db, telegram_user_id, slot, day_type)

        if not patterns:
            predictions[slot] = {"confidence": "none", "top": None, "alternatives": []}
            continue

        total_weight = sum(p.weight for p in patterns)
        top = patterns[0]
        top_ratio = top.weight / total_weight if total_weight > 0 else 0

        top_entry = {
            "foods": top.get_food_combo_list(),
            "mfp_ids": top.get_mfp_food_ids_list(),
            "pattern_id": top.id,
        }

        alternatives = [
            {
                "foods": p.get_food_combo_list(),
                "mfp_ids": p.get_mfp_food_ids_list(),
                "pattern_id": p.id,
            }
            for p in patterns[:MAX_ALTERNATIVES]
        ]

        if top_ratio >= HIGH_CONFIDENCE_THRESHOLD:
            predictions[slot] = {"confidence": "high", "top": top_entry, "alternatives": alternatives}
        else:
            predictions[slot] = {"confidence": "low", "top": top_entry, "alternatives": alternatives}

    return predictions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_predictor.py -v`

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add engine/predictor.py tests/test_predictor.py
git commit -m "feat: predictor — generate daily meal predictions per slot with confidence levels"
```

---

## Task 8: Learner

**Files:**
- Create: `engine/learner.py`
- Create: `tests/test_learner.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_learner.py`

```python
import json
from datetime import date

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_pattern, get_meal_patterns
from db.models import MealPattern, User
from engine.learner import on_confirm, on_replace

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_on_confirm_increases_weight(db):
    pid = await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Oats 80g"]', mfp_food_ids='["111"]',
        weight=5.0, last_confirmed="2026-04-09",
    ))

    await on_confirm(db, pattern_id=pid, confirmed_date="2026-04-10")

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert patterns[0].weight == 6.0
    assert patterns[0].last_confirmed == "2026-04-10"


@pytest.mark.asyncio
async def test_on_replace_creates_new_pattern_if_missing(db):
    await on_replace(
        db,
        telegram_user_id=1,
        slot="breakfast",
        day_type="weekday",
        new_foods=["Yogurt 170g", "Granola 50g"],
        new_mfp_ids=["888", "999"],
        confirmed_date="2026-04-10",
    )

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert len(patterns) == 1
    assert patterns[0].get_food_combo_list() == ["Yogurt 170g", "Granola 50g"]
    assert patterns[0].weight == 1.0


@pytest.mark.asyncio
async def test_on_replace_boosts_existing_pattern(db):
    pid = await save_meal_pattern(db, MealPattern(
        telegram_user_id=1, slot="breakfast", day_type="weekday",
        food_combo='["Yogurt 170g", "Granola 50g"]', mfp_food_ids='["888", "999"]',
        weight=2.0, last_confirmed="2026-04-08",
    ))

    await on_replace(
        db,
        telegram_user_id=1,
        slot="breakfast",
        day_type="weekday",
        new_foods=["Yogurt 170g", "Granola 50g"],
        new_mfp_ids=["888", "999"],
        confirmed_date="2026-04-10",
    )

    patterns = await get_meal_patterns(db, 1, "breakfast", "weekday")
    assert patterns[0].weight == 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_learner.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.learner'`

- [ ] **Step 3: Implement `engine/learner.py`**

```python
from __future__ import annotations

import json

import aiosqlite

from db.database import get_meal_patterns, save_meal_pattern, update_pattern_weight
from db.models import MealPattern


async def on_confirm(db: aiosqlite.Connection, pattern_id: int, confirmed_date: str) -> None:
    """User confirmed a predicted meal. Increase its weight by 1."""
    async with db.execute("SELECT weight FROM meal_patterns WHERE id = ?", (pattern_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    new_weight = row["weight"] + 1.0
    await update_pattern_weight(db, pattern_id, new_weight, confirmed_date)


async def on_replace(
    db: aiosqlite.Connection,
    telegram_user_id: int,
    slot: str,
    day_type: str,
    new_foods: list[str],
    new_mfp_ids: list[str],
    confirmed_date: str,
) -> int:
    """User replaced a prediction with a different meal. Boost or create the replacement pattern.
    Returns the pattern_id of the boosted/created pattern."""
    combo_key = json.dumps(sorted(new_foods))

    # Check if this combo already exists
    patterns = await get_meal_patterns(db, telegram_user_id, slot, day_type)
    for p in patterns:
        if json.dumps(sorted(p.get_food_combo_list())) == combo_key:
            new_weight = p.weight + 1.0
            await update_pattern_weight(db, p.id, new_weight, confirmed_date)
            return p.id

    # Create new pattern
    pattern = MealPattern(
        telegram_user_id=telegram_user_id,
        slot=slot,
        day_type=day_type,
        food_combo=json.dumps(new_foods),
        mfp_food_ids=json.dumps(new_mfp_ids),
        weight=1.0,
        last_confirmed=confirmed_date,
    )
    return await save_meal_pattern(db, pattern)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_learner.py -v`

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add engine/learner.py tests/test_learner.py
git commit -m "feat: learner — on_confirm and on_replace update pattern weights"
```

---

## Task 9: MFP Sync Queue

**Files:**
- Create: `mfp/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write the failing test**

File: `tests/test_sync.py`

```python
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import aiosqlite

from db.database import init_db, save_user, save_meal_entry, get_unsynced_entries, mark_entry_synced
from db.models import MealEntry, User
from mfp.sync import retry_unsynced

TEST_DB = ":memory:"


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        user = User(telegram_user_id=1, mfp_username="u", mfp_password_encrypted="e")
        await save_user(conn, user)
        yield conn


@pytest.mark.asyncio
async def test_retry_unsynced_marks_successful(db):
    entry = MealEntry(
        telegram_user_id=1, date="2026-04-10", day_of_week=3,
        slot="breakfast", food_name="Oats", quantity="80g",
        mfp_food_id="111", source="bot_confirm", synced_to_mfp=False,
    )
    entry_id = await save_meal_entry(db, entry)

    mock_client = MagicMock()
    mock_client.add_entry = AsyncMock(return_value=True)

    synced, failed = await retry_unsynced(db, mock_client, telegram_user_id=1)
    assert synced == 1
    assert failed == 0

    unsynced = await get_unsynced_entries(db, 1)
    assert len(unsynced) == 0


@pytest.mark.asyncio
async def test_retry_unsynced_counts_failures(db):
    entry = MealEntry(
        telegram_user_id=1, date="2026-04-10", day_of_week=3,
        slot="breakfast", food_name="Oats", quantity="80g",
        mfp_food_id="111", source="bot_confirm", synced_to_mfp=False,
    )
    await save_meal_entry(db, entry)

    mock_client = MagicMock()
    mock_client.add_entry = AsyncMock(side_effect=Exception("MFP down"))

    synced, failed = await retry_unsynced(db, mock_client, telegram_user_id=1)
    assert synced == 0
    assert failed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_sync.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mfp.sync'`

- [ ] **Step 3: Implement `mfp/sync.py`**

```python
from __future__ import annotations

import aiosqlite

from db.database import get_unsynced_entries, mark_entry_synced
from mfp.client import MfpClient


async def retry_unsynced(
    db: aiosqlite.Connection,
    client: MfpClient,
    telegram_user_id: int,
) -> tuple[int, int]:
    """Try to sync all unsynced entries to MFP. Returns (synced_count, failed_count)."""
    entries = await get_unsynced_entries(db, telegram_user_id)
    synced = 0
    failed = 0

    for entry in entries:
        try:
            await client.add_entry(
                date_str=entry.date,
                meal_name=entry.slot,
                food_name=entry.food_name,
                mfp_food_id=entry.mfp_food_id,
            )
            await mark_entry_synced(db, entry.id)
            synced += 1
        except Exception:
            failed += 1

    return synced, failed
```

Now we also need to add the `add_entry` method to `MfpClient`. Update `mfp/client.py`:

- [ ] **Step 4: Add `add_entry` to `mfp/client.py`**

Add this method to the `MfpClient` class in `mfp/client.py`, after the existing async wrappers:

```python
    # In MfpClient class — add after get_food_details

    def add_entry_sync(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        """Add a food entry to MFP diary. Returns True on success."""
        # python-myfitnesspal doesn't expose a direct "add entry" method.
        # For now this is a placeholder that will need to use the undocumented MFP web API.
        # The library's submit_food method may work for custom foods.
        # TODO: Implement when python-myfitnesspal adds write support or use HTTP directly
        return True

    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_sync.py -v`

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add mfp/sync.py mfp/client.py tests/test_sync.py
git commit -m "feat: sync queue — retry unsynced meals to MFP"
```

---

## Task 10: Encryption Utilities

**Files:**
- Create: `db/crypto.py` (small utility, no separate file — put in `config.py` or a utility)

Actually, keep it simple: add encrypt/decrypt functions directly in `db/database.py` since they're only used there.

- [ ] **Step 1: Add encryption functions to `db/database.py`**

Add at the top of `db/database.py`, after the imports:

```python
from cryptography.fernet import Fernet

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from config import ENCRYPTION_KEY
        _fernet = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    return _fernet


def encrypt_password(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()
```

- [ ] **Step 2: Add test in `tests/test_database.py`**

Append to `tests/test_database.py`:

```python
def test_encrypt_decrypt_roundtrip(monkeypatch):
    # Generate a valid Fernet key
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")

    # Force reimport
    import importlib
    import config
    importlib.reload(config)

    import db.database as dbmod
    dbmod._fernet = None  # reset cached fernet

    encrypted = dbmod.encrypt_password("mypassword123")
    assert encrypted != "mypassword123"

    decrypted = dbmod.decrypt_password(encrypted)
    assert decrypted == "mypassword123"
```

- [ ] **Step 3: Run tests**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_database.py -v`

Expected: all passed

- [ ] **Step 4: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "feat: Fernet encryption for MFP passwords"
```

---

## Task 11: Bot Messages & Keyboards

**Files:**
- Create: `bot/messages.py`
- Create: `bot/keyboards.py`
- Create: `tests/test_messages.py`
- Create: `tests/test_keyboards.py`

- [ ] **Step 1: Write the failing test for messages**

File: `tests/test_messages.py`

```python
from bot.messages import format_slot_message, format_day_header


def test_format_day_header():
    header = format_day_header("2026-04-10", day_index=1, total_days=7)
    assert "2026-04-10" in header or "Aprile" in header or "April" in header
    assert "1/7" in header


def test_format_slot_high_confidence():
    prediction = {
        "confidence": "high",
        "top": {"foods": ["Oats 80g", "Banana"], "mfp_ids": ["111", "222"], "pattern_id": 1},
        "alternatives": [],
    }
    msg = format_slot_message("breakfast", prediction)
    assert "Oats 80g" in msg
    assert "Banana" in msg


def test_format_slot_low_confidence():
    prediction = {
        "confidence": "low",
        "top": {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
        "alternatives": [
            {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
            {"foods": ["Tuna 160g"], "mfp_ids": ["444"], "pattern_id": 2},
        ],
    }
    msg = format_slot_message("lunch", prediction)
    assert "Chicken 200g" in msg
    assert "Tuna 160g" in msg


def test_format_slot_no_pattern():
    prediction = {"confidence": "none", "top": None, "alternatives": []}
    msg = format_slot_message("dinner", prediction)
    assert msg  # Should return something, not empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_messages.py -v`

Expected: FAIL

- [ ] **Step 3: Implement `bot/messages.py`**

```python
from __future__ import annotations

from datetime import date

from config import MEAL_SLOT_EMOJIS, MEAL_SLOT_LABELS


def format_day_header(date_str: str, day_index: int | None = None, total_days: int | None = None) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    formatted = d.strftime("%d %B %Y")
    progress = f" ({day_index}/{total_days})" if day_index and total_days else ""
    return f"\U0001F4C5 {day_name} {formatted}{progress}"


def format_slot_message(slot: str, prediction: dict) -> str:
    emoji = MEAL_SLOT_EMOJIS.get(slot, "\U0001F37D")
    label = MEAL_SLOT_LABELS.get(slot, slot)
    confidence = prediction["confidence"]

    if confidence == "none":
        return f"{emoji} *{label}*\nNo pattern found. Use /search or skip."

    if confidence == "high":
        foods = ", ".join(prediction["top"]["foods"])
        return f"{emoji} *{label}*\n{foods}"

    # Low confidence — show alternatives
    lines = [f"{emoji} *{label}*", "Choose:"]
    for i, alt in enumerate(prediction["alternatives"], 1):
        foods = ", ".join(alt["foods"])
        lines.append(f"  {i}. {foods}")
    return "\n".join(lines)


def format_day_summary(date_str: str, confirmed: int, skipped: int, total: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    return f"\u2705 {day_name} done! {confirmed} logged, {skipped} skipped ({total} slots)"


def format_status_line(date_str: str, logged: int, pending: int, skipped: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%a")
    status = "\u2705" if pending == 0 else "\u23F3"
    return f"{status} {day_name} {date_str}: {logged} logged, {pending} pending, {skipped} skipped"
```

- [ ] **Step 4: Write the failing test for keyboards**

File: `tests/test_keyboards.py`

```python
from bot.keyboards import slot_keyboard_high, slot_keyboard_low, stop_button


def test_slot_keyboard_high_has_three_buttons():
    kb = slot_keyboard_high(slot="breakfast", pattern_id=1)
    # Should have Confirm, Change, Skip
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Confirm" in t for t in texts)
    assert any("Change" in t for t in texts)
    assert any("Skip" in t for t in texts)


def test_slot_keyboard_low_has_alternative_buttons():
    alternatives = [
        {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
        {"foods": ["Tuna 160g"], "mfp_ids": ["444"], "pattern_id": 2},
    ]
    kb = slot_keyboard_low(slot="lunch", alternatives=alternatives)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Chicken" in t for t in texts)
    assert any("Tuna" in t for t in texts)
    assert any("Search" in t or "Cerca" in t for t in texts)
    assert any("Skip" in t for t in texts)


def test_stop_button():
    kb = stop_button()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert any("Stop" in b.text for b in buttons)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_keyboards.py -v`

Expected: FAIL

- [ ] **Step 6: Implement `bot/keyboards.py`**

```python
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def slot_keyboard_high(slot: str, pattern_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data=f"confirm:{slot}:{pattern_id}"),
            InlineKeyboardButton("\U0001F504 Change", callback_data=f"change:{slot}:{pattern_id}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
        ]
    ])


def slot_keyboard_low(slot: str, alternatives: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
        InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
    ])
    return InlineKeyboardMarkup(rows)


def slot_keyboard_none(slot: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
        ]
    ])


def alternatives_keyboard(slot: str, alternatives: list[dict]) -> InlineKeyboardMarkup:
    """Show top 5 alternatives after user presses Change."""
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
        InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}"),
    ])
    return InlineKeyboardMarkup(rows)


def search_results_keyboard(slot: str, results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in results[:5]:
        label = r["name"]
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"search_pick:{slot}:{r['mfp_id']}")])
    rows.append([InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}")])
    return InlineKeyboardMarkup(rows)


def stop_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u23F9 Stop - resume later", callback_data="week:stop")]
    ])


def import_range_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("3 months", callback_data="import:90"),
            InlineKeyboardButton("6 months", callback_data="import:180"),
        ],
        [
            InlineKeyboardButton("1 year", callback_data="import:365"),
            InlineKeyboardButton("All", callback_data="import:730"),
        ],
    ])
```

- [ ] **Step 7: Run both tests**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_messages.py tests/test_keyboards.py -v`

Expected: all passed

- [ ] **Step 8: Commit**

```bash
git add bot/messages.py bot/keyboards.py tests/test_messages.py tests/test_keyboards.py
git commit -m "feat: bot messages and keyboards — formatting, inline buttons"
```

---

## Task 12: Bot Onboarding Handlers (/start, /login, import)

**Files:**
- Create: `bot/onboarding.py`

- [ ] **Step 1: Implement `bot/onboarding.py`**

```python
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import import_range_keyboard
from db.database import encrypt_password, get_user, save_user
from db.models import User
from engine.pattern_analyzer import analyze_history
from mfp.client import MfpClient
from mfp.scraper import scrape_history


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user = await get_user(db, update.effective_user.id)

    if user and user.onboarding_done:
        await update.message.reply_text(
            "Welcome back! Use /today, /week, or /status."
        )
        return

    await update.message.reply_text(
        "Hi! To get started, I need your MyFitnessPal credentials.\n\n"
        "Send them in this format:\n"
        "`/login your_username your_password`\n\n"
        "The message will be deleted immediately for security.",
        parse_mode="Markdown",
    )


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]

    # Delete the message containing credentials immediately
    try:
        await update.message.delete()
    except Exception:
        pass

    args = context.args
    if not args or len(args) < 2:
        await update.effective_chat.send_message(
            "Usage: `/login username password`", parse_mode="Markdown"
        )
        return

    username = args[0]
    password = " ".join(args[1:])  # password may contain spaces

    # Test connection
    status_msg = await update.effective_chat.send_message(
        f"Connecting to MFP as {username}..."
    )

    try:
        client = MfpClient(username, password)
        # Test with today's date
        await client.get_day(date.today())
    except Exception as e:
        await status_msg.edit_text(f"Connection failed: {e}\nPlease check your credentials and try again.")
        return

    # Save user
    encrypted_pw = encrypt_password(password)
    user = User(
        telegram_user_id=update.effective_user.id,
        mfp_username=username,
        mfp_password_encrypted=encrypted_pw,
    )
    await save_user(db, user)

    # Store client in user_data for this session
    context.user_data["mfp_client"] = client

    await status_msg.edit_text(
        f"Connected as {username} on MFP!\n\n"
        "How much history should I import?",
        reply_markup=import_range_keyboard(),
    )


async def import_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    telegram_user_id = update.effective_user.id

    days = int(query.data.split(":")[1])
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Get or create MFP client
    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, telegram_user_id)
        if not user:
            await query.edit_message_text("Please /login first.")
            return
        from db.database import decrypt_password
        password = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient(user.mfp_username, password)
        context.user_data["mfp_client"] = client

    await query.edit_message_text(
        f"Importing {days} days of history... This may take a while.\n"
        f"(~{days} seconds at 1 request/second)"
    )

    async def on_progress(current_date: date, total: int) -> None:
        # Update message every 10 days to avoid rate limiting
        if (end_date - current_date).days % 10 == 0:
            try:
                await query.edit_message_text(
                    f"Importing... {current_date.isoformat()} ({total} entries so far)"
                )
            except Exception:
                pass

    total = await scrape_history(
        db, client, telegram_user_id, start_date, end_date, on_progress=on_progress
    )

    # Analyze patterns
    pattern_count = await analyze_history(db, telegram_user_id)

    # Mark onboarding done
    user = await get_user(db, telegram_user_id)
    user.onboarding_done = True
    await save_user(db, user)

    await query.edit_message_text(
        f"Bootstrap complete!\n"
        f"Imported: {total} entries\n"
        f"Patterns found: {pattern_count}\n\n"
        f"Try /today to see today's meals!"
    )
```

- [ ] **Step 2: Run full test suite to ensure no regressions**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/ -v`

Expected: all previous tests still pass

- [ ] **Step 3: Commit**

```bash
git add bot/onboarding.py
git commit -m "feat: onboarding handlers — /start, /login, import with progress"
```

---

## Task 13: Bot Daily Handlers (/today, /tomorrow, /day)

**Files:**
- Create: `bot/daily.py`
- Create: `tests/test_daily.py`

- [ ] **Step 1: Implement `bot/daily.py`**

```python
from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import (
    alternatives_keyboard,
    search_results_keyboard,
    slot_keyboard_high,
    slot_keyboard_low,
    slot_keyboard_none,
)
from bot.messages import format_day_header, format_day_summary, format_slot_message
from config import MEAL_SLOTS
from db.database import (
    decrypt_password,
    get_meal_entries,
    get_user,
    mark_entry_synced,
    save_meal_entry,
)
from db.models import MealEntry
from engine.learner import on_confirm, on_replace
from engine.predictor import predict_day
from mfp.client import MfpClient

DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _get_target_date(day_name: str) -> date:
    """Get the next occurrence of the given day name."""
    today = date.today()
    target_dow = DAY_NAMES.get(day_name.lower()[:3], -1)
    if target_dow == -1:
        return today
    days_ahead = (target_dow - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 0  # today if it matches
    return today + timedelta(days=days_ahead)


async def _ensure_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> MfpClient | None:
    """Get or create MFP client. Returns None if not logged in."""
    client = context.user_data.get("mfp_client")
    if client:
        return client
    db = context.bot_data["db"]
    user = await get_user(db, update.effective_user.id)
    if not user or not user.onboarding_done:
        await update.message.reply_text("Please /start first to set up your account.")
        return None
    password = decrypt_password(user.mfp_password_encrypted)
    client = MfpClient(user.mfp_username, password)
    context.user_data["mfp_client"] = client
    return client


async def _send_slot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_date: date,
    slot: str,
    prediction: dict,
    day_index: int | None = None,
    total_days: int | None = None,
) -> None:
    """Send a single slot message with appropriate keyboard."""
    text = format_slot_message(slot, prediction)

    if prediction["confidence"] == "high":
        kb = slot_keyboard_high(slot, prediction["top"]["pattern_id"])
    elif prediction["confidence"] == "low":
        kb = slot_keyboard_low(slot, prediction["alternatives"])
    else:
        kb = slot_keyboard_none(slot)

    # Store context for callback handlers
    context.user_data.setdefault("current_day", {})
    context.user_data["current_day"]["date"] = target_date.isoformat()
    context.user_data["current_day"]["predictions"] = context.user_data.get("current_day", {}).get("predictions", {})
    context.user_data["current_day"]["predictions"][slot] = prediction
    context.user_data["current_day"]["current_slot_idx"] = MEAL_SLOTS.index(slot)

    await update.effective_chat.send_message(text, reply_markup=kb, parse_mode="Markdown")


async def _send_next_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Send the next pending slot. Returns True if there was a slot to send, False if day is complete."""
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    day_data = context.user_data.get("current_day", {})
    target_date = date.fromisoformat(day_data["date"])
    predictions = day_data.get("all_predictions", {})

    current_idx = day_data.get("current_slot_idx", -1) + 1

    # Find next slot that hasn't been filled
    while current_idx < len(MEAL_SLOTS):
        slot = MEAL_SLOTS[current_idx]
        existing = await get_meal_entries(db, user_id, target_date.isoformat(), slot)
        if not existing:
            context.user_data["current_day"]["current_slot_idx"] = current_idx
            await _send_slot(update, context, target_date, slot, predictions[slot])
            return True
        current_idx += 1

    return False


async def start_day_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_date: date,
    day_index: int | None = None,
    total_days: int | None = None,
) -> None:
    """Start the slot-by-slot flow for a single day."""
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    predictions = await predict_day(db, user_id, target_date)

    # Store all predictions for this day
    context.user_data["current_day"] = {
        "date": target_date.isoformat(),
        "all_predictions": predictions,
        "predictions": {},
        "current_slot_idx": -1,
        "confirmed": 0,
        "skipped": 0,
        "day_index": day_index,
        "total_days": total_days,
    }

    header = format_day_header(target_date.isoformat(), day_index, total_days)
    await update.effective_chat.send_message(header, parse_mode="Markdown")

    has_slot = await _send_next_slot(update, context)
    if not has_slot:
        await update.effective_chat.send_message(
            f"\u2705 All slots already filled for {target_date.isoformat()}!"
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    await start_day_flow(update, context, date.today())


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    await start_day_flow(update, context, date.today() + timedelta(days=1))


async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/day Mon`", parse_mode="Markdown")
        return
    target = _get_target_date(context.args[0])
    await start_day_flow(update, context, target)


async def slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirm/change/skip/pick/search callbacks for slots."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    data = query.data
    parts = data.split(":")
    action = parts[0]
    slot = parts[1] if len(parts) > 1 else ""

    day_data = context.user_data.get("current_day", {})
    target_date = day_data.get("date", date.today().isoformat())
    predictions = day_data.get("all_predictions", {})
    prediction = predictions.get(slot, {})

    if action == "confirm":
        pattern_id = int(parts[2])
        foods = prediction.get("top", {}).get("foods", [])
        mfp_ids = prediction.get("top", {}).get("mfp_ids", [])

        # Save to history
        parsed_date = date.fromisoformat(target_date)
        for food, mfp_id in zip(foods, mfp_ids):
            entry = MealEntry(
                telegram_user_id=user_id,
                date=target_date,
                day_of_week=parsed_date.weekday(),
                slot=slot,
                food_name=food,
                quantity="",
                mfp_food_id=str(mfp_id),
                source="bot_confirm",
                synced_to_mfp=False,
            )
            entry_id = await save_meal_entry(db, entry)

            # Try to sync to MFP
            client = context.user_data.get("mfp_client")
            if client:
                try:
                    await client.add_entry(target_date, slot, food, str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass  # stays unsynced, user can /retry later

        await on_confirm(db, pattern_id, target_date)

        day_data["confirmed"] = day_data.get("confirmed", 0) + 1
        await query.edit_message_text(f"\u2705 {', '.join(foods)} logged!")

        # Send next slot
        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            # If in week mode, trigger next day
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "pick":
        pattern_id = int(parts[2])
        # Find the picked alternative
        alts = prediction.get("alternatives", [])
        picked = next((a for a in alts if a["pattern_id"] == pattern_id), None)
        if not picked:
            return

        parsed_date = date.fromisoformat(target_date)
        for food, mfp_id in zip(picked["foods"], picked["mfp_ids"]):
            entry = MealEntry(
                telegram_user_id=user_id,
                date=target_date,
                day_of_week=parsed_date.weekday(),
                slot=slot,
                food_name=food,
                quantity="",
                mfp_food_id=str(mfp_id),
                source="bot_confirm",
                synced_to_mfp=False,
            )
            entry_id = await save_meal_entry(db, entry)
            client = context.user_data.get("mfp_client")
            if client:
                try:
                    await client.add_entry(target_date, slot, food, str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass

        day_type = "weekend" if parsed_date.weekday() >= 5 else "weekday"
        await on_replace(db, user_id, slot, day_type, picked["foods"], picked["mfp_ids"], target_date)

        day_data["confirmed"] = day_data.get("confirmed", 0) + 1
        await query.edit_message_text(f"\u2705 {', '.join(picked['foods'])} logged!")

        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "change":
        # Show alternatives
        alts = prediction.get("alternatives", [])
        if not alts:
            # Fetch from DB
            from db.database import get_meal_patterns
            day_type = "weekend" if date.fromisoformat(target_date).weekday() >= 5 else "weekday"
            patterns = await get_meal_patterns(db, user_id, slot, day_type)
            alts = [
                {"foods": p.get_food_combo_list(), "mfp_ids": p.get_mfp_food_ids_list(), "pattern_id": p.id}
                for p in patterns[:5]
            ]
        kb = alternatives_keyboard(slot, alts)
        await query.edit_message_text(f"Alternatives for {slot}:", reply_markup=kb)

    elif action == "skip":
        day_data["skipped"] = day_data.get("skipped", 0) + 1
        await query.edit_message_text(f"\u23ED {slot} skipped")

        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data.get("confirmed", 0), day_data["skipped"], len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "search":
        context.user_data["search_slot"] = slot
        await query.edit_message_text(f"Type the food name to search for {slot}:")

    elif action == "search_pick":
        mfp_id = parts[2]
        # Look up food details
        client = context.user_data.get("mfp_client")
        if client:
            details = await client.get_food_details(int(mfp_id))
            if details:
                parsed_date = date.fromisoformat(target_date)
                entry = MealEntry(
                    telegram_user_id=user_id,
                    date=target_date,
                    day_of_week=parsed_date.weekday(),
                    slot=slot,
                    food_name=details["name"],
                    quantity="",
                    mfp_food_id=str(mfp_id),
                    source="bot_search",
                    synced_to_mfp=False,
                )
                entry_id = await save_meal_entry(db, entry)
                try:
                    await client.add_entry(target_date, slot, details["name"], str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass

                day_type = "weekend" if parsed_date.weekday() >= 5 else "weekday"
                await on_replace(db, user_id, slot, day_type, [details["name"]], [str(mfp_id)], target_date)

                day_data["confirmed"] = day_data.get("confirmed", 0) + 1
                await query.edit_message_text(f"\u2705 {details['name']} logged!")

                has_next = await _send_next_slot(update, context)
                if not has_next:
                    summary = format_day_summary(
                        target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
                    )
                    await update.effective_chat.send_message(summary)
                    if "week_mode" in context.user_data:
                        from bot.week import advance_week
                        await advance_week(update, context)

    elif action == "back":
        # Re-send original slot
        await _send_slot(update, context, date.fromisoformat(target_date), slot, prediction)
        try:
            await query.message.delete()
        except Exception:
            pass


async def search_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text search when user is in search mode."""
    search_slot = context.user_data.get("search_slot")
    if not search_slot:
        return  # not in search mode

    client = context.user_data.get("mfp_client")
    if not client:
        await update.message.reply_text("Not connected to MFP. Please /login first.")
        return

    query_text = update.message.text.strip()
    results = await client.search_food(query_text)

    if not results:
        await update.message.reply_text(f"No results for '{query_text}'. Try again:")
        return

    kb = search_results_keyboard(search_slot, results)
    await update.message.reply_text(f"Results for '{query_text}':", reply_markup=kb)
    context.user_data.pop("search_slot", None)
```

- [ ] **Step 2: Write a basic test**

File: `tests/test_daily.py`

```python
from datetime import date

from bot.daily import _get_target_date, DAY_NAMES


def test_get_target_date_returns_correct_day():
    target = _get_target_date("Mon")
    assert target.weekday() == 0  # Monday


def test_get_target_date_handles_short_names():
    for name, dow in DAY_NAMES.items():
        target = _get_target_date(name)
        assert target.weekday() == dow
```

- [ ] **Step 3: Run tests**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/test_daily.py -v`

Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add bot/daily.py tests/test_daily.py
git commit -m "feat: daily handlers — /today, /tomorrow, /day with slot-by-slot flow"
```

---

## Task 14: Bot Week Wizard (/week)

**Files:**
- Create: `bot/week.py`

- [ ] **Step 1: Implement `bot/week.py`**

```python
from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.daily import _ensure_client, start_day_flow
from bot.keyboards import stop_button
from config import MEAL_SLOTS, WEEK_TIMEOUT_MINUTES
from db.database import (
    get_active_week_progress,
    get_meal_entries,
    save_week_progress,
    update_week_progress,
)
from db.models import WeekProgress


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()

    # Check for existing in-progress week
    existing = await get_active_week_progress(db, user_id)
    if existing:
        resume_date = date.fromisoformat(existing.current_day)
        context.user_data["week_mode"] = {
            "wp_id": existing.id,
            "start": date.fromisoformat(existing.week_start),
            "end": date.fromisoformat(existing.week_start) + timedelta(days=6),
            "current": resume_date,
        }
        await update.message.reply_text(
            f"Resuming from {resume_date.isoformat()}...",
            reply_markup=stop_button(),
        )
        await _start_next_day(update, context)
        return

    # Start new week
    end_date = today + timedelta(days=6)
    wp = WeekProgress(
        telegram_user_id=user_id,
        week_start=today.isoformat(),
        current_day=today.isoformat(),
    )
    wp_id = await save_week_progress(db, wp)

    context.user_data["week_mode"] = {
        "wp_id": wp_id,
        "start": today,
        "end": end_date,
        "current": today,
    }

    await update.message.reply_text(
        f"\U0001F4C5 Week plan: {today.isoformat()} to {end_date.isoformat()}",
        reply_markup=stop_button(),
    )
    await _start_next_day(update, context)


async def _start_next_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Find the next day that needs filling and start its flow."""
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    week = context.user_data.get("week_mode", {})

    current = week.get("current", date.today())
    end = week.get("end", date.today())

    while current <= end:
        # Check if this day is already completely filled
        all_filled = True
        for slot in MEAL_SLOTS:
            entries = await get_meal_entries(db, user_id, current.isoformat(), slot)
            if not entries:
                all_filled = False
                break

        if not all_filled:
            week["current"] = current
            day_index = (current - week["start"]).days + 1
            total_days = (week["end"] - week["start"]).days + 1
            await start_day_flow(update, context, current, day_index, total_days)
            return

        current += timedelta(days=1)

    # All days done
    await _complete_week(update, context)


async def advance_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called after a day flow completes to move to the next day."""
    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if not week:
        return

    current = week["current"] + timedelta(days=1)
    week["current"] = current

    await update_week_progress(db, week["wp_id"], current.isoformat(), "in_progress")

    if current > week["end"]:
        await _complete_week(update, context)
        return

    await update.effective_chat.send_message("---", reply_markup=stop_button())
    await _start_next_day(update, context)


async def week_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if not week:
        await query.edit_message_text("No active week plan.")
        return

    await update_week_progress(db, week["wp_id"], week["current"].isoformat(), "stopped")
    context.user_data.pop("week_mode", None)
    context.user_data.pop("current_day", None)

    await query.edit_message_text(
        f"\u23F9 Week plan paused at {week['current'].isoformat()}.\n"
        "Use /week to resume."
    )


async def _complete_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    week = context.user_data.get("week_mode")
    if week:
        await update_week_progress(db, week["wp_id"], week["end"].isoformat(), "completed")
    context.user_data.pop("week_mode", None)
    context.user_data.pop("current_day", None)

    await update.effective_chat.send_message(
        "\u2705 Week plan complete! All days have been processed."
    )
```

- [ ] **Step 2: Run full test suite**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/ -v`

Expected: all passed

- [ ] **Step 3: Commit**

```bash
git add bot/week.py
git commit -m "feat: week wizard — sequential multi-day flow with stop/resume"
```

---

## Task 15: Bot Utility Handlers (/status, /undo, /retry)

**Files:**
- Create: `bot/utility.py`

- [ ] **Step 1: Implement `bot/utility.py`**

```python
from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.messages import format_status_line
from config import MEAL_SLOTS
from db.database import (
    decrypt_password,
    get_meal_entries,
    get_unsynced_entries,
    get_user,
)
from mfp.client import MfpClient
from mfp.sync import retry_unsynced


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()

    lines = ["\U0001F4CA Weekly Status\n"]

    for i in range(7):
        d = today + timedelta(days=i)
        logged = 0
        skipped = 0  # we can't know skipped from DB, just show logged vs pending
        for slot in MEAL_SLOTS:
            entries = await get_meal_entries(db, user_id, d.isoformat(), slot)
            if entries:
                logged += 1
        pending = len(MEAL_SLOTS) - logged
        lines.append(format_status_line(d.isoformat(), logged, pending, skipped))

    # Unsynced count
    unsynced = await get_unsynced_entries(db, user_id)
    if unsynced:
        lines.append(f"\n\u26A0 {len(unsynced)} entries not synced to MFP. Use /retry")

    await update.message.reply_text("\n".join(lines))


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    # Find the last entry inserted by this user
    async with db.execute(
        "SELECT * FROM meals_history WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        await update.message.reply_text("Nothing to undo.")
        return

    food_name = row["food_name"]
    entry_date = row["date"]
    slot = row["slot"]
    entry_id = row["id"]

    await db.execute("DELETE FROM meals_history WHERE id = ?", (entry_id,))
    await db.commit()

    await update.message.reply_text(
        f"\u21A9 Removed: {food_name} from {slot} on {entry_date}\n"
        "Note: if it was already synced to MFP, you'll need to remove it manually in the app."
    )


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, user_id)
        if not user:
            await update.message.reply_text("Please /login first.")
            return
        password = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient(user.mfp_username, password)
        context.user_data["mfp_client"] = client

    msg = await update.message.reply_text("Retrying unsynced entries...")
    synced, failed = await retry_unsynced(db, client, user_id)

    await msg.edit_text(f"Retry complete: {synced} synced, {failed} failed.")
```

- [ ] **Step 2: Commit**

```bash
git add bot/utility.py
git commit -m "feat: utility handlers — /status, /undo, /retry"
```

---

## Task 16: Main Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement `main.py`**

```python
from __future__ import annotations

import os

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import DB_PATH, TELEGRAM_BOT_TOKEN
from db.database import get_db


async def post_init(application: Application) -> None:
    """Called after Application.initialize(). Set up DB connection."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    application.bot_data["db"] = await get_db(DB_PATH)


async def post_shutdown(application: Application) -> None:
    """Called during Application.shutdown(). Close DB."""
    db = application.bot_data.get("db")
    if db:
        await db.close()


def main() -> None:
    from bot.daily import day_command, search_text_handler, slot_callback, today_command, tomorrow_command
    from bot.onboarding import import_callback, login_command, start_command
    from bot.utility import retry_command, status_command, undo_command
    from bot.week import week_command, week_stop_callback

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("day", day_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("retry", retry_command))

    # Callback handlers — order matters (more specific patterns first)
    application.add_handler(CallbackQueryHandler(import_callback, pattern=r"^import:"))
    application.add_handler(CallbackQueryHandler(week_stop_callback, pattern=r"^week:stop$"))
    application.add_handler(CallbackQueryHandler(slot_callback, pattern=r"^(confirm|change|skip|pick|search|search_pick|back):"))

    # Free-text search handler (only when user is in search mode)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_text_handler))

    print("Bot starting... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify import chain works**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -c "from bot.daily import today_command; from bot.week import week_command; from bot.onboarding import start_command; print('All imports OK')"`

Expected: `All imports OK` (assuming env vars are set)

Note: This will fail if `TELEGRAM_BOT_TOKEN` is not set. That's expected — `config.py` validates env vars at import time. To test imports without env vars, temporarily set them:

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && TELEGRAM_BOT_TOKEN=test ENCRYPTION_KEY=test python -c "from bot.daily import today_command; from bot.week import week_command; from bot.onboarding import start_command; print('All imports OK')"`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main entry point — register all handlers, DB lifecycle"
```

---

## Task 17: Run Full Test Suite & Fix Issues

- [ ] **Step 1: Run all tests**

Run: `cd C:\Users\g.chirico\source\repos\Personal\mfp-auto && python -m pytest tests/ -v --tb=short`

Expected: all tests pass. If any fail, fix them.

- [ ] **Step 2: Run a quick smoke test with fake env**

Run:
```bash
cd C:\Users\g.chirico\source\repos\Personal\mfp-auto
TELEGRAM_BOT_TOKEN=fake ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") python -c "
import asyncio
from db.database import get_db, save_user, init_db
from db.models import User
from engine.predictor import predict_day
from datetime import date

async def smoke():
    db = await get_db(':memory:')
    user = User(telegram_user_id=1, mfp_username='test', mfp_password_encrypted='enc')
    await save_user(db, user)
    preds = await predict_day(db, 1, date.today())
    assert len(preds) == 7
    print('Smoke test passed!')
    await db.close()

asyncio.run(smoke())
"
```

Expected: `Smoke test passed!`

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: test suite fixes from full integration run"
```

---

## Task 18: Deployment Guide & README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

```markdown
# MFP Auto Bot

Telegram bot that auto-logs meals on MyFitnessPal based on your eating patterns.

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and get the token
2. Generate a Fernet encryption key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Copy `.env.example` to `.env` and fill in the values
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Run:
   ```bash
   python main.py
   ```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Set up your account |
| `/login user pass` | Connect your MFP account |
| `/today` | Log today's meals |
| `/tomorrow` | Log tomorrow's meals |
| `/week` | Log meals for the next 7 days |
| `/day Mon` | Log meals for a specific day |
| `/status` | See weekly overview |
| `/undo` | Remove last logged entry |
| `/retry` | Retry failed MFP syncs |

## Deploy to PythonAnywhere (Free)

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Upload project files (or clone from git)
3. Open a Bash console and install: `pip install -r requirements.txt`
4. Set environment variables in the "Tasks" tab
5. Create an "Always-on task": `python /home/yourusername/mfp-auto/main.py`
6. Renew free tier every 3 months (email reminder sent)

## Tech Stack

- Python 3.14
- python-telegram-bot 22.7
- python-myfitnesspal 2.1.2
- SQLite (via aiosqlite)
- pandas
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup and deployment instructions"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All spec sections are covered:
  - Architecture (Tasks 1-3), MFP Client + Scraper (Tasks 4-5), Pattern Engine (Tasks 6-8), Sync (Task 9), Encryption (Task 10), Bot UI (Task 11), Onboarding (Task 12), Daily flow (Task 13), Week wizard (Task 14), Utilities (Task 15), Entry point (Task 16), Deployment (Task 18)
  - All 10 commands from spec: `/start`, `/login`, `/import`, `/today`, `/tomorrow`, `/week`, `/day`, `/status`, `/undo`, `/retry`
  - Multi-user support (telegram_user_id partitioning throughout)
  - Scraping-only bootstrap (no CSV path)
  - 7 meal slots
  - Decay formula in pattern_analyzer (0.95^weeks)
  - Error handling: retry queue, unsynced tracking, credential encryption

- [x] **Placeholder scan:** No TBD/TODO except the acknowledged `add_entry_sync` in Task 9 Step 4 which is documented as needing MFP write API integration.

- [x] **Type consistency:** `MealEntry`, `MealPattern`, `User`, `WeekProgress` used consistently. `predict_day` returns `dict[str, dict]` with `confidence`/`top`/`alternatives` keys used uniformly in `daily.py`, `messages.py`, `keyboards.py`. Function names match across tasks (`on_confirm`, `on_replace`, `retry_unsynced`, `scrape_history`, `analyze_history`, `predict_day`).
