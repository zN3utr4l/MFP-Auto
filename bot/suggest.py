from __future__ import annotations

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from config import MEAL_SLOTS
from db.database import get_meal_patterns


def _filter_suggestions(foods: list[dict], remaining: dict) -> list[dict]:
    """Filter foods that fit within remaining macro budget, sorted by protein desc."""
    fits = []
    for f in foods:
        n = f.get("nutrition", {})
        if (n.get("calories", 0) <= remaining.get("calories", 0)
                and n.get("protein", 0) <= remaining.get("protein", 0) + 5
                and n.get("carbs", 0) <= remaining.get("carbs", 0) + 5
                and n.get("fat", 0) <= remaining.get("fat", 0) + 5):
            fits.append(f)
    fits.sort(key=lambda f: f.get("nutrition", {}).get("protein", 0), reverse=True)
    return fits[:5]


async def suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client

    client = await _ensure_client(update, context)
    if not client:
        return

    goals = context.user_data.get("macro_goals")
    if not goals:
        goals = await client.get_nutrient_goals()
        if goals:
            context.user_data["macro_goals"] = goals
    if not goals:
        await update.message.reply_text("Could not fetch your macro goals.")
        return

    totals = await client.get_day_totals(date.today())
    remaining = {
        "calories": goals["calories"] - totals["calories"],
        "protein": goals["protein"] - totals["protein"],
        "carbs": goals["carbs"] - totals["carbs"],
        "fat": goals["fat"] - totals["fat"],
    }

    if remaining["calories"] <= 0:
        await update.message.reply_text("You've already hit your calorie goal for today!")
        return

    msg = await update.message.reply_text("Analyzing your foods...")

    db = context.bot_data["db"]
    user_id = update.effective_user.id

    # Collect unique foods from all patterns
    all_foods: dict[str, dict] = {}
    for day_type in ("weekday", "weekend"):
        for slot in MEAL_SLOTS:
            patterns = await get_meal_patterns(db, user_id, slot, day_type)
            for p in patterns:
                for food_name, mfp_id in zip(p.get_food_combo_list(), p.get_mfp_food_ids_list()):
                    if mfp_id and mfp_id not in all_foods:
                        all_foods[mfp_id] = {"name": food_name, "mfp_id": mfp_id}

    # Fetch nutrition for each unique food (cap at 20)
    foods_with_nutrition = []
    for mfp_id, food in list(all_foods.items())[:20]:
        results = await client.search_food(food["name"])
        for r in results:
            if str(r["mfp_id"]) == str(mfp_id):
                foods_with_nutrition.append({"name": food["name"], "nutrition": r.get("nutrition", {})})
                break

    suggestions = _filter_suggestions(foods_with_nutrition, remaining)

    if not suggestions:
        await msg.edit_text(
            f"Remaining: {remaining['calories']:.0f} cal, {remaining['protein']:.0f}g P, "
            f"{remaining['carbs']:.0f}g C, {remaining['fat']:.0f}g F\n\n"
            "No foods from your history fit. Try /today to search manually."
        )
        return

    lines = [
        f"Remaining: {remaining['calories']:.0f} cal, {remaining['protein']:.0f}g P, "
        f"{remaining['carbs']:.0f}g C, {remaining['fat']:.0f}g F\n",
        "Suggested from your foods:",
    ]
    for i, s in enumerate(suggestions, 1):
        n = s["nutrition"]
        lines.append(
            f"  {i}. {s['name']} ({n['calories']:.0f} cal, "
            f"{n['protein']:.0f}g P, {n['carbs']:.0f}g C, {n['fat']:.0f}g F)"
        )

    await msg.edit_text("\n".join(lines))
