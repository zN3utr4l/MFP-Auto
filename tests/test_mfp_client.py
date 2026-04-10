from unittest.mock import MagicMock, patch
from datetime import date

import pytest

from mfp.client import MfpClient


@pytest.fixture
def client():
    """Create an MfpClient without actually logging in."""
    c = MfpClient("testuser", "testpass")
    c._logged_in = True
    c._effective_username = "testuser"
    c._access_token = "fake-token"
    c._user_id = "12345"
    return c


def test_mfp_client_creation():
    client = MfpClient("testuser", "testpass")
    assert client._username == "testuser"
    assert not client._logged_in


def test_get_day_parses_html(client):
    html = """
    <html><body><table>
    <tr class="meal_header"><td>Breakfast</td><td>Calories</td><td>Fat</td></tr>
    <tr><td><a>Oats 80g</a></td><td>300</td><td>5</td></tr>
    <tr class="total"><td>Totals</td><td>300</td><td>5</td></tr>
    </table></body></html>
    """
    mock_resp = MagicMock()
    mock_resp.content = html.encode("utf8")
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 10))

    assert len(result) == 1
    assert result[0]["meal_name"] == "Breakfast"
    assert result[0]["entries"][0]["name"] == "Oats 80g"


def test_get_day_handles_multiple_meals(client):
    html = """
    <html><body><table>
    <tr class="meal_header"><td>Breakfast</td><td>Calories</td></tr>
    <tr><td><a>Oats</a></td><td>300</td></tr>
    <tr class="total"><td>Totals</td><td>300</td></tr>
    <tr class="meal_header"><td>Lunch</td><td>Calories</td></tr>
    <tr><td><a>Rice</a></td><td>400</td></tr>
    <tr class="total"><td>Totals</td><td>400</td></tr>
    </table></body></html>
    """
    mock_resp = MagicMock()
    mock_resp.content = html.encode("utf8")
    client.session.get = MagicMock(return_value=mock_resp)

    result = client.get_day_sync(date(2026, 4, 10))

    assert len(result) == 2
    assert result[0]["meal_name"] == "Breakfast"
    assert result[1]["meal_name"] == "Lunch"
