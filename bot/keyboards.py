from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _callback_suffix(date_str: str = "", flow_id: str = "") -> str:
    suffix = f":{date_str}" if date_str else ""
    if flow_id:
        suffix += f":{flow_id}"
    return suffix


def slot_keyboard_high(
    slot: str,
    pattern_id: int,
    date_str: str = "",
    flow_id: str = "",
) -> InlineKeyboardMarkup:
    d = _callback_suffix(date_str, flow_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data=f"confirm:{slot}:{pattern_id}{d}"),
            InlineKeyboardButton("\U0001F504 Change", callback_data=f"change:{slot}:{pattern_id}{d}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}{d}"),
        ]
    ])


def slot_keyboard_low(
    slot: str,
    alternatives: list[dict],
    date_str: str = "",
    flow_id: str = "",
) -> InlineKeyboardMarkup:
    d = _callback_suffix(date_str, flow_id)
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}{d}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}{d}"),
        InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}{d}"),
    ])
    return InlineKeyboardMarkup(rows)


def slot_keyboard_none(slot: str, date_str: str = "", flow_id: str = "") -> InlineKeyboardMarkup:
    d = _callback_suffix(date_str, flow_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}{d}"),
            InlineKeyboardButton("\u23ED Skip", callback_data=f"skip:{slot}{d}"),
        ]
    ])


def alternatives_keyboard(
    slot: str,
    alternatives: list[dict],
    date_str: str = "",
    flow_id: str = "",
) -> InlineKeyboardMarkup:
    """Show top 5 alternatives after user presses Change."""
    d = _callback_suffix(date_str, flow_id)
    rows = []
    for alt in alternatives:
        label = ", ".join(alt["foods"])
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"pick:{slot}:{alt['pattern_id']}{d}")])

    rows.append([
        InlineKeyboardButton("\U0001F50D Search", callback_data=f"search:{slot}{d}"),
        InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}{d}"),
    ])
    return InlineKeyboardMarkup(rows)


def search_results_keyboard(
    slot: str,
    results: list[dict],
    date_str: str = "",
    flow_id: str = "",
) -> InlineKeyboardMarkup:
    d = _callback_suffix(date_str, flow_id)
    rows = []
    for r in results[:5]:
        label = r["name"]
        if len(label) > 40:
            label = label[:37] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"search_pick:{slot}:{r['mfp_id']}{d}")])
    rows.append([InlineKeyboardButton("\u2B05 Back", callback_data=f"back:{slot}{d}")])
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


def serving_size_keyboard(callback_prefix: str, serving_sizes: list[dict]) -> InlineKeyboardMarkup:
    """Show serving_size options as buttons."""
    rows = []
    for ss in serving_sizes[:6]:
        label = f"{ss.get('value', 1)} {ss['unit']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}:{ss['index']}")])
    return InlineKeyboardMarkup(rows)


def servings_keyboard(callback_prefix: str, serving_size_index: int) -> InlineKeyboardMarkup:
    """Show quick quantity buttons + custom option."""
    amounts = [0.5, 1, 1.5, 2]
    buttons = [
        InlineKeyboardButton(str(a), callback_data=f"{callback_prefix}:{serving_size_index}:{a}")
        for a in amounts
    ]
    buttons.append(InlineKeyboardButton("custom", callback_data=f"{callback_prefix}:{serving_size_index}:custom"))
    return InlineKeyboardMarkup([buttons])
