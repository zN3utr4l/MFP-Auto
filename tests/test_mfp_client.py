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
