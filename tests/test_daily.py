from datetime import date

from bot.daily import _get_target_date, DAY_NAMES


def test_get_target_date_returns_correct_day():
    target = _get_target_date("Mon")
    assert target.weekday() == 0  # Monday


def test_get_target_date_handles_short_names():
    for name, dow in DAY_NAMES.items():
        target = _get_target_date(name)
        assert target.weekday() == dow
