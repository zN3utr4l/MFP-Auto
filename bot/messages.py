from __future__ import annotations

from datetime import date

from config import MEAL_SLOT_EMOJIS, MEAL_SLOT_LABELS


def format_day_header(date_str: str, day_index: int | None = None, total_days: int | None = None) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    formatted = d.strftime("%d %B %Y")
    progress = f"  ({day_index}/{total_days})" if day_index and total_days else ""
    return f"\U0001F4C5 *{day_name} {formatted}*{progress}"


def format_slot_message(slot: str, prediction: dict) -> str:
    emoji = MEAL_SLOT_EMOJIS.get(slot, "\U0001F37D")
    label = MEAL_SLOT_LABELS.get(slot, slot)
    confidence = prediction["confidence"]

    if confidence == "none":
        return f"{emoji} *{label}*\nNo pattern yet — search or skip"

    if confidence == "high":
        foods = ", ".join(prediction["top"]["foods"])
        si = prediction.get("top", {}).get("serving_info", {})
        if isinstance(si, list) and si:
            si = si[0]
        if isinstance(si, dict) and si.get("servings") and si.get("serving_unit"):
            qty = f" ({si['servings']} {si['serving_unit']})"
        else:
            qty = ""
        return f"{emoji} *{label}*\n{foods}{qty}"

    # Low confidence
    lines = [f"{emoji} *{label}*\nPick one:"]
    for i, alt in enumerate(prediction["alternatives"], 1):
        foods = ", ".join(alt["foods"])
        lines.append(f"  {i}. {foods}")
    return "\n".join(lines)


def format_day_summary(date_str: str, confirmed: int, skipped: int, total: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    parts = [f"\U0001F3C1 *{day_name} done!*"]
    parts.append(f"\u2705 {confirmed} logged")
    if skipped:
        parts.append(f"\u23ED {skipped} skipped")
    return "\n".join(parts)


def format_macro_summary(totals: dict, goals: dict) -> str:
    if not goals or not goals.get("calories"):
        return ""

    lines = []
    over_any = False

    for emoji, label, key, unit in [
        ("\U0001F525", "Cal", "calories", ""),
        ("\U0001F4AA", "Pro", "protein", "g"),
        ("\U0001F35E", "Carb", "carbs", "g"),
        ("\U0001FAD2", "Fat", "fat", "g"),
    ]:
        current = totals.get(key, 0)
        goal = goals.get(key, 0)
        if goal <= 0:
            continue

        remaining = goal - current
        bar = _progress_bar(current, goal)

        if current > goal:
            over_any = True
            lines.append(f"{emoji} {label}  {bar}  {current:.0f}/{goal:.0f}{unit} (*+{-remaining:.0f}*)")
        elif remaining <= goal * 0.15:
            lines.append(f"{emoji} {label}  {bar}  {current:.0f}/{goal:.0f}{unit} (_{remaining:.0f} left_)")
        else:
            lines.append(f"{emoji} {label}  {bar}  {current:.0f}/{goal:.0f}{unit}")

    if not lines:
        return ""

    if over_any:
        header = "\u26A0\uFE0F *Over budget — adjust next meals*"
    else:
        header = "\U0001F4CA *Today's macros*"
    return header + "\n\n" + "\n".join(lines)


def _progress_bar(current: float, goal: float, length: int = 10) -> str:
    if goal <= 0:
        return ""
    ratio = min(current / goal, 1.0)
    filled = round(ratio * length)
    return "\u2588" * filled + "\u2591" * (length - filled)


def format_history(days: list[dict], goals: dict) -> str:
    if not days:
        return "No data available."

    lines = ["\U0001F4C8 *Last 7 days*\n"]
    sum_cal, sum_p, sum_c, sum_f = 0.0, 0.0, 0.0, 0.0

    for day in days:
        d = date.fromisoformat(day["date"])
        t = day["totals"]
        cal, p, c, f = t["calories"], t["protein"], t["carbs"], t["fat"]
        sum_cal += cal
        sum_p += p
        sum_c += c
        sum_f += f

        marker = ""
        if goals and goals.get("calories"):
            over = (cal > goals["calories"] * 1.05 or f > goals["fat"] * 1.05)
            on_target = (not over and cal >= goals["calories"] * 0.90
                         and p >= goals["protein"] * 0.90)
            if over:
                marker = " \u274C"
            elif on_target:
                marker = " \u2705"

        lines.append(
            f"`{d.strftime('%a %d')}` {cal:.0f} cal  "
            f"P:{p:.0f}  C:{c:.0f}  F:{f:.0f}{marker}"
        )

    n = len(days)
    lines.append("")
    lines.append(
        f"\U0001F4CA *Avg:* {sum_cal/n:.0f} cal  "
        f"P:{sum_p/n:.0f}  C:{sum_c/n:.0f}  F:{sum_f/n:.0f}"
    )
    if goals and goals.get("calories"):
        lines.append(
            f"\U0001F3AF *Goal:* {goals['calories']:.0f} cal  "
            f"P:{goals['protein']:.0f}  C:{goals['carbs']:.0f}  F:{goals['fat']:.0f}"
        )

    return "\n".join(lines)


def format_status_line(date_str: str, logged: int, pending: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%a")
    if pending == 0:
        return f"\u2705 `{day_name} {date_str}`  {logged} logged"
    return f"\u23F3 `{day_name} {date_str}`  {logged}/{logged + pending} slots"


def format_filled_slot(slot: str, foods: list[str], macros: dict) -> str:
    """Format a single already-filled slot for the /today header."""
    from bot.daily import _clean_food_name

    emoji = MEAL_SLOT_EMOJIS.get(slot, "")
    label = MEAL_SLOT_LABELS.get(slot, slot)
    cal = macros.get("calories", 0)
    p = macros.get("protein", 0)
    c = macros.get("carbs", 0)
    f = macros.get("fat", 0)

    lines = [f"{emoji} *{label}*  _{cal:.0f}cal  P:{p:.0f}  C:{c:.0f}  F:{f:.0f}_"]

    if foods and not (len(foods) == 1 and "cal)" in foods[0]):
        for food in foods[:4]:
            lines.append(f"  \u2022 {_clean_food_name(food)}")
        if len(foods) > 4:
            lines.append(f"  _...+{len(foods) - 4} more_")

    return "\n".join(lines)
