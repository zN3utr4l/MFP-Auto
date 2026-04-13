from bot.suggest import _filter_suggestions


def test_filter_suggestions_within_budget():
    remaining = {"calories": 500, "protein": 50, "carbs": 60, "fat": 20}
    foods = [
        {"name": "Chicken", "nutrition": {"calories": 250, "protein": 46, "carbs": 0, "fat": 5}},
        {"name": "Pizza", "nutrition": {"calories": 800, "protein": 30, "carbs": 90, "fat": 35}},
        {"name": "Yogurt", "nutrition": {"calories": 130, "protein": 12, "carbs": 5, "fat": 4}},
    ]
    result = _filter_suggestions(foods, remaining)
    names = [r["name"] for r in result]
    assert "Chicken" in names
    assert "Yogurt" in names
    assert "Pizza" not in names


def test_filter_suggestions_sorted_by_protein():
    remaining = {"calories": 1000, "protein": 100, "carbs": 200, "fat": 50}
    foods = [
        {"name": "Rice", "nutrition": {"calories": 200, "protein": 4, "carbs": 45, "fat": 0}},
        {"name": "Chicken", "nutrition": {"calories": 250, "protein": 46, "carbs": 0, "fat": 5}},
    ]
    result = _filter_suggestions(foods, remaining)
    assert result[0]["name"] == "Chicken"
