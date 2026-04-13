from __future__ import annotations

from datetime import date

from config import MEAL_SLOT_EMOJIS, MEAL_SLOT_LABELS


def format_day_header(date_str: str, day_index: int | None = None, total_days: int | None = None) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    formatted = d.strftime("%d %B %Y")
    progress = f" ({day_index}/{total_days})" if day_index and total_days else ""
    return f"\U0001F4C5 {day_name} {formatted}{progress}"


def format_slot_message(slot: str, prediction: dict) -> str:
    emoji = MEAL_SLOT_EMOJIS.get(slot, "\U0001F37D")
    label = MEAL_SLOT_LABELS.get(slot, slot)
    confidence = prediction["confidence"]

    if confidence == "none":
        return f"{emoji} *{label}*\nNo pattern found. Use /search or skip."

    if confidence == "high":
        foods = ", ".join(prediction["top"]["foods"])
        return f"{emoji} *{label}*\n{foods}"

    # Low confidence — show alternatives
    lines = [f"{emoji} *{label}*", "Choose:"]
    for i, alt in enumerate(prediction["alternatives"], 1):
        foods = ", ".join(alt["foods"])
        lines.append(f"  {i}. {foods}")
    return "\n".join(lines)


def format_day_summary(date_str: str, confirmed: int, skipped: int, total: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%A")
    return f"\u2705 {day_name} done! {confirmed} logged, {skipped} skipped ({total} slots)"


def format_macro_summary(totals: dict, goals: dict) -> str:
    """Format a macro progress summary comparing current totals to goals.

    Returns empty string if goals are not available.
    """
    if not goals or not goals.get("calories"):
        return ""

    lines = []
    over_any = False

    for label, key, unit in [
        ("Cal", "calories", ""),
        ("Protein", "protein", "g"),
        ("Carbs", "carbs", "g"),
        ("Fat", "fat", "g"),
    ]:
        current = totals.get(key, 0)
        goal = goals.get(key, 0)
        if goal <= 0:
            continue

        pct = current / goal * 100
        remaining = goal - current

        if current > goal:
            over_any = True
            lines.append(f"  {label}: {current:.0f}/{goal:.0f}{unit} (+{-remaining:.0f} over)")
        elif pct >= 90:
            lines.append(f"  {label}: {current:.0f}/{goal:.0f}{unit} ({remaining:.0f} left)")
        else:
            lines.append(f"  {label}: {current:.0f}/{goal:.0f}{unit}")

    if not lines:
        return ""

    header = "Daily macros:" if not over_any else "Daily macros (adjust next meals):"
    return header + "\n" + "\n".join(lines)


def format_history(days: list[dict], goals: dict) -> str:
    """Format a 7-day macro history with averages."""
    if not days:
        return "No data available."

    lines = ["Weekly history:"]
    sum_cal, sum_p, sum_c, sum_f = 0.0, 0.0, 0.0, 0.0

    for day in days:
        d = date.fromisoformat(day["date"])
        t = day["totals"]
        cal, p, c, f = t["calories"], t["protein"], t["carbs"], t["fat"]
        sum_cal += cal
        sum_p += p
        sum_c += c
        sum_f += f

        over = False
        on_target = False
        if goals and goals.get("calories"):
            over = (cal > goals["calories"] * 1.05 or p > goals["protein"] * 1.05
                    or c > goals["carbs"] * 1.05 or f > goals["fat"] * 1.05)
            if not over:
                on_target = cal >= goals["calories"] * 0.95 and p >= goals["protein"] * 0.95

        marker = " over" if over else (" ok" if on_target else "")
        lines.append(f"  {d.strftime('%a %d')}: {cal:.0f} cal | P:{p:.0f} C:{c:.0f} F:{f:.0f}{marker}")

    n = len(days)
    lines.append(f"\nAverage: {sum_cal/n:.0f} cal | P:{sum_p/n:.0f} C:{sum_c/n:.0f} F:{sum_f/n:.0f}")
    if goals and goals.get("calories"):
        lines.append(f"Target:  {goals['calories']:.0f} cal | P:{goals['protein']:.0f} C:{goals['carbs']:.0f} F:{goals['fat']:.0f}")

    return "\n".join(lines)


def format_status_line(date_str: str, logged: int, pending: int, skipped: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%a")
    status = "\u2705" if pending == 0 else "\u23F3"
    return f"{status} {day_name} {date_str}: {logged} logged, {pending} pending, {skipped} skipped"
