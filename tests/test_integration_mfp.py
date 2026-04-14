"""Integration tests against the real MyFitnessPal API.

Requires .env with:
  MFP_AUTH_JSON — the JSON from https://www.myfitnesspal.com/user/auth_token?refresh=true

All tests are skipped if this env var is missing.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest
from dotenv import load_dotenv

load_dotenv()

MFP_AUTH_JSON = os.environ.get("MFP_AUTH_JSON", "")

needs_mfp = pytest.mark.skipif(
    not MFP_AUTH_JSON or MFP_AUTH_JSON.startswith("{\"access_token\":\"..."),
    reason="MFP_AUTH_JSON required (real token from MFP auth page)",
)


def _client():
    from mfp.client import MfpClient

    return MfpClient.from_auth_json(MFP_AUTH_JSON)


# ── Auth ──────────────────────────────────────────────────────────


@needs_mfp
def test_mfp_validate_token():
    """MFP token is valid and returns a username."""
    client = _client()
    username = client.validate_sync()
    assert username  # non-empty string
    assert len(username) > 0
    print(f"  MFP user: {username}")


@needs_mfp
def test_mfp_get_username_cached():
    """Second call to get_username uses cache."""
    client = _client()
    name1 = client.get_username_sync()
    name2 = client.get_username_sync()
    assert name1 == name2


# ── Read Diary ────────────────────────────────────────────────────


@needs_mfp
def test_mfp_get_day_today():
    """Fetch today's diary — should not error even if empty."""
    client = _client()
    meals = client.get_day_sync(date.today())
    assert isinstance(meals, list)
    print(f"  Today: {len(meals)} meals")
    for m in meals:
        assert "meal_name" in m
        assert "entries" in m
        print(f"    {m['meal_name']}: {len(m['entries'])} entries")


@needs_mfp
def test_mfp_get_day_yesterday():
    """Fetch yesterday's diary (more likely to have data)."""
    client = _client()
    yesterday = date.today() - timedelta(days=1)
    meals = client.get_day_sync(yesterday)
    assert isinstance(meals, list)
    for m in meals:
        for entry in m["entries"]:
            assert "name" in entry
            assert "mfp_id" in entry
            print(f"    {m['meal_name']}: {entry['name']} (id={entry['mfp_id']})")


@needs_mfp
def test_mfp_get_day_returns_individual_entries():
    """If diary has data, verify entries have food names not just calorie summaries."""
    client = _client()
    # Check last 7 days for any day with data
    for i in range(7):
        d = date.today() - timedelta(days=i)
        meals = client.get_day_sync(d)
        for m in meals:
            if m["entries"]:
                entry = m["entries"][0]
                name = entry["name"]
                # If entry parsing works, names should NOT be "Meal (X cal)" format
                # (unless fallback was triggered)
                if " cal)" in name and name.startswith(m["meal_name"]):
                    pytest.fail(
                        f"Got meal summary instead of individual entry: {name}. "
                        "read_diary endpoint may not be working."
                    )
                assert entry.get("mfp_id") is not None, f"Entry missing mfp_id: {name}"
                print(f"  {d} {m['meal_name']}: {name} (id={entry['mfp_id']}) OK")
                return

    pytest.skip("No diary entries in the last 7 days")


# ── Search ────────────────────────────────────────────────────────


@needs_mfp
def test_mfp_search_food():
    """Search for a common food and get results."""
    client = _client()
    results = client.search_food_sync("banana")
    assert len(results) > 0
    first = results[0]
    assert "name" in first
    assert "mfp_id" in first
    assert first["mfp_id"] is not None
    print(f"  Found {len(results)} results, first: {first['name']} (id={first['mfp_id']})")


@needs_mfp
def test_mfp_search_returns_mfp_ids():
    """All search results have usable mfp_id values."""
    client = _client()
    results = client.search_food_sync("chicken breast")
    for r in results[:5]:
        assert r["mfp_id"], f"Missing mfp_id for {r['name']}"


@needs_mfp
def test_mfp_get_food_details():
    """Fetch details for a food found via search."""
    client = _client()
    results = client.search_food_sync("oatmeal")
    assert results, "No search results"

    food = results[0]
    details = client.get_food_details_sync(int(food["mfp_id"]), hint_name=food["name"])
    assert details is not None
    assert details["name"]
    print(f"  Details: {details['name']} (id={details['mfp_id']})")


# ── Write Diary ───────────────────────────────────────────────────


@needs_mfp
def test_mfp_add_entry():
    """Add a real entry to MFP diary (uses a far-future date to avoid polluting real data)."""
    client = _client()

    # Search for a known food to get a valid ID
    results = client.search_food_sync("banana")
    assert results, "No search results for 'banana'"
    food = results[0]

    # Use a date far in the future to not pollute real diary
    test_date = (date.today() + timedelta(days=365)).isoformat()

    result = client.add_entry_sync(
        date_str=test_date,
        meal_name="breakfast",
        food_name=food["name"],
        mfp_food_id=str(food["mfp_id"]),
    )
    assert result is True
    print(f"  Added '{food['name']}' to {test_date} breakfast OK")


@needs_mfp
def test_mfp_add_entry_no_food_id_raises():
    """Adding entry without food ID raises ValueError (not an API call)."""
    client = _client()
    with pytest.raises(ValueError, match="No food ID"):
        client.add_entry_sync("2026-04-13", "lunch", "Unknown Food", "")


# ── Full Flow ─────────────────────────────────────────────────────


@needs_mfp
def test_mfp_search_then_add_flow():
    """Simulate the real user flow: search → pick → add to diary."""
    client = _client()

    # 1. Search
    results = client.search_food_sync("greek yogurt")
    assert results, "No search results"
    picked = results[0]
    print(f"  Searched: {picked['name']} (id={picked['mfp_id']})")

    # 2. Add to diary (far future date)
    test_date = (date.today() + timedelta(days=366)).isoformat()
    result = client.add_entry_sync(
        date_str=test_date,
        meal_name="morning_snack",
        food_name=picked["name"],
        mfp_food_id=str(picked["mfp_id"]),
    )
    assert result is True

    # 3. Read back — verify it appears
    read_date = date.fromisoformat(test_date)
    meals = client.get_day_sync(read_date)
    all_entries = [e for m in meals for e in m["entries"]]
    print(f"  Read back {test_date}: {len(all_entries)} entries")
    # At minimum, the day should now have entries
    assert len(all_entries) > 0, "Entry was added but not visible in diary"
