from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def slot_keyboard_high(slot: str, pattern_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data=f"confirm:{slot}:{pattern_id}"),
            InlineKeyboardButton("\U0001F504 Change", callback_data=f"change:{slot}:{pattern_id}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
        ]
    ])


def slot_keyboard_low(slot: str, alternatives: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
        InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
    ])
    return InlineKeyboardMarkup(rows)


def slot_keyboard_none(slot: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}"),
        ]
    ])


def alternatives_keyboard(slot: str, alternatives: list[dict]) -> InlineKeyboardMarkup:
    """Show top 5 alternatives after user presses Change."""
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}"),
        InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}"),
    ])
    return InlineKeyboardMarkup(rows)


def search_results_keyboard(slot: str, results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in results[:5]:
        label = r["name"]
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"search_pick:{slot}:{r['mfp_id']}")])
    rows.append([InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}")])
    return InlineKeyboardMarkup(rows)


def stop_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u23F9 Stop - resume later", callback_data="week:stop")]
    ])


def import_range_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("3 months", callback_data="import:90"),
            InlineKeyboardButton("6 months", callback_data="import:180"),
        ],
        [
            InlineKeyboardButton("1 year", callback_data="import:365"),
            InlineKeyboardButton("All", callback_data="import:730"),
        ],
    ])
