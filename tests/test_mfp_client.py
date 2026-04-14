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


def test_get_day_uses_read_diary(client):
    """get_day_sync uses v2/diary/read_diary to get individual food entries."""
    read_diary_response = {
        "items": [
            {
                "type": "food_entry",
                "meal_name": "Breakfast",
                "food": {"id": 111, "description": "Oatmeal"},
                "servings": 1.0,
                "serving_size": {"value": 100, "unit": "g", "nutrition_multiplier": 1.0},
                "nutritional_contents": {"energy": {"value": 300}, "protein": 10},
            },
            {
                "type": "food_entry",
                "meal_name": "Breakfast",
                "food": {"id": 222, "description": "Banana"},
                "servings": 1.0,
                "serving_size": {"value": 1, "unit": "medium", "nutrition_multiplier": 1.18},
                "nutritional_contents": {"energy": {"value": 105}, "protein": 1.3},
            },
            {
                "type": "food_entry",
                "meal_name": "Lunch",
                "food": {"id": 333, "description": "Chicken breast"},
                "servings": 1.5,
                "serving_size": {"value": 100, "unit": "g"},
                "nutritional_contents": {"energy": {"value": 248}, "protein": 46},
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = read_diary_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 9))

    assert len(result) == 2  # Breakfast and Lunch
    assert result[0]["meal_name"] == "Breakfast"
    assert len(result[0]["entries"]) == 2
    assert result[0]["entries"][0]["name"] == "Oatmeal"
    assert result[0]["entries"][0]["mfp_id"] == 111
    assert result[0]["entries"][1]["name"] == "Banana"
    assert result[1]["meal_name"] == "Lunch"
    assert result[1]["entries"][0]["name"] == "Chicken breast"


def test_get_day_falls_back_to_summary(client):
    """When read_diary fails, falls back to v2/diary meal summaries."""
    # First call (read_diary) raises, second call (v2/diary) returns summaries
    summary_response = {
        "items": [
            {
                "type": "diary_meal",
                "diary_meal": "Breakfast",
                "nutritional_contents": {"energy": {"value": 300}},
            },
        ]
    }

    call_count = 0

    def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if "read_diary" in url:
            resp.raise_for_status.side_effect = Exception("404")
            return resp
        resp.json.return_value = summary_response
        resp.raise_for_status = MagicMock()
        return resp

    client.session.get = mock_get

    result = client.get_day_sync(date(2026, 4, 9))

    assert call_count == 2  # tried read_diary, then fallback
    assert len(result) == 1
    assert result[0]["meal_name"] == "Breakfast"
    assert result[0]["entries"][0]["name"] == "Breakfast (300 cal)"


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
    # Mock the lookup (GET) to return serving_sizes
    lookup_resp = MagicMock()
    lookup_resp.json.return_value = {"items": [{"item": {
        "id": "12345", "version": "v1",
        "serving_sizes": [{"index": 0, "value": 1.0, "unit": "medium", "nutrition_multiplier": 1.0}],
    }}]}
    lookup_resp.raise_for_status = MagicMock()

    # Mock the POST
    post_resp = MagicMock()
    post_resp.json.return_value = {"items": [{"id": "abc"}]}
    post_resp.raise_for_status = MagicMock()
    post_resp.ok = True

    client.session.get = MagicMock(return_value=lookup_resp)
    client.session.post = MagicMock(return_value=post_resp)

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


@pytest.mark.asyncio
async def test_get_food_details_async_forwards_hint_name(client):
    client.get_food_details_sync = MagicMock(return_value={"name": "Oatmeal", "mfp_id": 123})

    result = await client.get_food_details(123, hint_name="oatmeal")

    assert result == {"name": "Oatmeal", "mfp_id": 123}
    client.get_food_details_sync.assert_called_once_with(123, "oatmeal")
