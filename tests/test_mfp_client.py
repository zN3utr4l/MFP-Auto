import json
from unittest.mock import MagicMock
from datetime import date

import pytest

from mfp.client import MfpClient


@pytest.fixture
def client():
    c = MfpClient(access_token="fake-token", user_id="12345")
    c._username = "testuser"
    return c


def test_from_auth_json():
    auth = json.dumps({"access_token": "tok123", "user_id": "uid456"})
    client = MfpClient.from_auth_json(auth)
    assert client._access_token == "tok123"
    assert client._user_id == "uid456"


def test_get_day_parses_api_response(client):
    api_response = {
        "items": [
            {
                "type": "diary_meal",
                "date": "2026-04-09",
                "diary_meal": "Breakfast",
                "nutritional_contents": {
                    "energy": {"unit": "calories", "value": 300.0},
                    "protein": 10.0,
                },
            },
            {
                "type": "diary_meal",
                "date": "2026-04-09",
                "diary_meal": "Lunch",
                "nutritional_contents": {
                    "energy": {"unit": "calories", "value": 500.0},
                    "protein": 30.0,
                },
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 9))

    assert len(result) == 2
    assert result[0]["meal_name"] == "Breakfast"
    assert result[0]["entries"][0]["name"] == "Breakfast (300 cal)"
    assert result[1]["meal_name"] == "Lunch"


def test_get_day_parses_individual_entries(client):
    """When API returns diary_entries nested inside meals, parse individual foods."""
    api_response = {
        "items": [
            {
                "type": "diary_meal",
                "diary_meal": "Breakfast",
                "nutritional_contents": {"energy": {"value": 500}},
                "diary_entries": [
                    {
                        "food": {"id": 111, "description": "Oatmeal"},
                        "serving_quantity": "80g",
                        "nutritional_contents": {"energy": {"value": 300}},
                    },
                    {
                        "food": {"id": 222, "description": "Banana"},
                        "serving_quantity": "1 medium",
                        "nutritional_contents": {"energy": {"value": 200}},
                    },
                ],
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 9))

    assert len(result) == 1
    entries = result[0]["entries"]
    assert len(entries) == 2
    assert entries[0]["name"] == "Oatmeal"
    assert entries[0]["mfp_id"] == 111
    assert entries[1]["name"] == "Banana"


def test_search_food_returns_serving_sizes_and_nutrition(client):
    api_response = {
        "items": [{
            "item": {
                "id": "123", "description": "Oatmeal", "version": "456",
                "serving_sizes": [
                    {"index": 0, "value": 1.0, "unit": "cup", "nutrition_multiplier": 1.0},
                    {"index": 1, "value": 100.0, "unit": "g", "nutrition_multiplier": 0.83},
                ],
                "nutritional_contents": {
                    "energy": {"value": 150, "unit": "calories"},
                    "protein": 5.0, "carbohydrates": 27.0, "fat": 3.0,
                },
            }
        }]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    results = client.search_food_sync("oatmeal")
    assert len(results) == 1
    assert results[0]["name"] == "Oatmeal"
    assert len(results[0]["serving_sizes"]) == 2
    assert results[0]["serving_sizes"][0]["unit"] == "cup"
    assert results[0]["nutrition"]["protein"] == 5.0
    assert results[0]["version"] == "456"


def test_add_entry_posts_to_diary(client):
    """add_entry_sync sends correct payload to POST /v2/diary."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": [{"id": "abc"}]}
    mock_resp.raise_for_status = MagicMock()
    client.session.post = MagicMock(return_value=mock_resp)

    result = client.add_entry_sync("2026-04-13", "breakfast", "Oatmeal", "12345")

    assert result is True
    client.session.post.assert_called_once()
    call_kwargs = client.session.post.call_args
    payload = call_kwargs.kwargs["json"]
    item = payload["items"][0]
    assert item["type"] == "food_entry"
    assert item["date"] == "2026-04-13"
    assert item["meal_position"] == 0  # breakfast
    assert item["food"]["id"] == "12345"


def test_add_entry_raises_on_empty_food_id(client):
    """add_entry_sync raises ValueError when food ID is missing."""
    with pytest.raises(ValueError, match="No food ID"):
        client.add_entry_sync("2026-04-13", "lunch", "Something", "")

    with pytest.raises(ValueError, match="No food ID"):
        client.add_entry_sync("2026-04-13", "lunch", "Something", "None")


def test_get_day_skips_empty_meals(client):
    api_response = {
        "items": [
            {
                "type": "diary_meal",
                "date": "2026-04-09",
                "diary_meal": "Breakfast",
                "nutritional_contents": {
                    "energy": {"unit": "calories", "value": 0},
                },
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 9))

    assert len(result) == 1
    assert result[0]["entries"] == []  # 0 cal = no entries
