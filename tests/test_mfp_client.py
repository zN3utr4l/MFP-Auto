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
