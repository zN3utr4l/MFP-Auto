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
