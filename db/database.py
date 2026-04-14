from __future__ import annotations

import aiosqlite
from cryptography.fernet import Fernet

from db.models import MealEntry, MealPattern, User, WeekProgress

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
    serving_info TEXT NOT NULL DEFAULT '{}',
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
    updated_at TEXT NOT NULL,
    serving_info TEXT NOT NULL DEFAULT '{}'
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
    await _ensure_column(db, "meals_history", "serving_info", "TEXT NOT NULL DEFAULT '{}'")
    await db.commit()


async def _ensure_column(
    db: aiosqlite.Connection,
    table: str,
    column: str,
    column_def: str,
) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        columns = [row["name"] async for row in cursor]
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


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
           (telegram_user_id, date, day_of_week, slot, food_name, quantity, serving_info,
            mfp_food_id, source, synced_to_mfp, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry.telegram_user_id, entry.date, entry.day_of_week, entry.slot,
         entry.food_name, entry.quantity, entry.serving_info, entry.mfp_food_id, entry.source,
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
                serving_info=row["serving_info"],
                source=row["source"],
                synced_to_mfp=bool(row["synced_to_mfp"]),
                created_at=row["created_at"],
            ))
    return entries


# --- Meal Patterns ---

async def save_meal_pattern(db: aiosqlite.Connection, pattern: MealPattern) -> int:
    cursor = await db.execute(
        """INSERT INTO meal_patterns
           (telegram_user_id, slot, day_type, food_combo, mfp_food_ids, weight, last_confirmed, updated_at, serving_info)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pattern.telegram_user_id, pattern.slot, pattern.day_type, pattern.food_combo,
         pattern.mfp_food_ids, pattern.weight, pattern.last_confirmed, pattern.updated_at, pattern.serving_info),
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
                serving_info=row["serving_info"],
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
                serving_info=row["serving_info"],
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
    from datetime import UTC, datetime
    await db.execute(
        "UPDATE week_progress SET current_day = ?, status = ?, updated_at = ? WHERE id = ?",
        (current_day, status, datetime.now(UTC).isoformat(), wp_id),
    )
    await db.commit()
