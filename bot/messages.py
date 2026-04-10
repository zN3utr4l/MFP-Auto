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


def format_status_line(date_str: str, logged: int, pending: int, skipped: int) -> str:
    d = date.fromisoformat(date_str)
    day_name = d.strftime("%a")
    status = "\u2705" if pending == 0 else "\u23F3"
    return f"{status} {day_name} {date_str}: {logged} logged, {pending} pending, {skipped} skipped"
