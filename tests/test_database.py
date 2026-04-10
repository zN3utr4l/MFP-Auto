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
