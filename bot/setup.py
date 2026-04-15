"""Setup wizard — register typical foods with serving sizes per slot.

Flow: /setup → for each of 7 slots → search → pick food → pick serving_size
→ pick quantity → add more or next slot → save patterns.
"""

from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.keyboards import serving_size_keyboard, servings_keyboard
from config import MEAL_SLOTS, MEAL_SLOT_EMOJIS, MEAL_SLOT_LABELS
from db.database import save_meal_pattern
from db.models import MealPattern


async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client

    client = await _ensure_client(update, context)
    if not client:
        return

    context.user_data["setup"] = {
        "slot_idx": 0,
        "foods": {},  # slot -> [{name, mfp_id, serving_info}, ...]
    }
    await update.message.reply_text(
        "Let's set up your typical meals!\n\n"
        "For each slot, search and pick your food, then choose portion size.\n"
        "You can add multiple foods per slot, or skip slots you don't use."
    )
    await _ask_slot(update, context)


async def _ask_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    setup = context.user_data.get("setup", {})
    idx = setup.get("slot_idx", 0)

    if idx >= len(MEAL_SLOTS):
        await _finish_setup(update, context)
        return

    slot = MEAL_SLOTS[idx]
    emoji = MEAL_SLOT_EMOJIS.get(slot, "")
    label = MEAL_SLOT_LABELS.get(slot, slot)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Skip this slot", callback_data=f"setup_skip:{slot}"),
    ]])
    context.user_data["setup_search_slot"] = slot

    await update.effective_chat.send_message(
        f"{emoji} *{label}* ({idx + 1}/{len(MEAL_SLOTS)})\n\n"
        "Type the food name to search, or skip:",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def setup_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text input during setup (food search or custom quantity)."""
    # Check for custom quantity input first
    pending = context.user_data.get("setup_pending_custom_qty")
    if pending:
        text = update.message.text.strip()
        try:
            amount = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Please enter a number (e.g. 0.8, 1.5):")
            return

        slot = pending["slot"]
        ss_index = pending["ss_index"]
        context.user_data.pop("setup_pending_custom_qty")
        await _save_food_with_serving(update, context, slot, ss_index, amount)
        return

    # Regular food search
    slot = context.user_data.get("setup_search_slot")
    if not slot:
        return

    client = context.user_data.get("mfp_client")
    if not client:
        return

    query = update.message.text.strip()
    results = await client.search_food(query)

    if not results:
        await update.message.reply_text(f"No results for '{query}'. Try again:")
        return

    rows = []
    for r in results[:8]:
        label = r["name"]
        if len(label) > 50:
            label = label[:47] + "..."
        rows.append([InlineKeyboardButton(
            label, callback_data=f"setup_pick:{slot}:{r['mfp_id']}"
        )])
    rows.append([
        InlineKeyboardButton("Search again", callback_data=f"setup_search_again:{slot}"),
        InlineKeyboardButton("Skip slot", callback_data=f"setup_skip:{slot}"),
    ])

    context.user_data["setup_search_results"] = {str(r["mfp_id"]): r for r in results[:8]}
    await update.message.reply_text(
        f"Results for '{query}':",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")
    action = parts[0]
    slot = parts[1] if len(parts) > 1 else ""
    setup = context.user_data.get("setup", {})

    if action == "setup_skip":
        context.user_data.pop("setup_search_slot", None)
        setup["slot_idx"] = setup.get("slot_idx", 0) + 1
        await query.edit_message_text(f"Skipped {MEAL_SLOT_LABELS.get(slot, slot)}")
        await _ask_slot(update, context)

    elif action == "setup_pick":
        mfp_id = parts[2]
        results = context.user_data.get("setup_search_results", {})
        picked = results.get(mfp_id)
        if not picked:
            return

        # Store pending food, show serving_size options
        context.user_data["setup_pending_food"] = picked
        ss_list = picked.get("serving_sizes", [])

        if ss_list:
            kb = serving_size_keyboard(f"setup_ss:{slot}", ss_list)
            await query.edit_message_text(
                f"*{picked['name']}*\nChoose portion size:",
                reply_markup=kb,
                parse_mode="Markdown",
            )
        else:
            # No serving_sizes available, use default
            await _save_food_with_serving(update, context, slot, None, 1.0)
            try:
                await query.edit_message_text(f"Added: {picked['name']} (1 serving)")
            except Exception:
                pass

    elif action == "setup_ss":
        # User picked a serving_size, show quantity buttons
        ss_index = int(parts[2])
        pending = context.user_data.get("setup_pending_food", {})
        ss_list = pending.get("serving_sizes", [])
        ss = next((s for s in ss_list if s.get("index") == ss_index), {})
        unit = ss.get("unit", "serving")

        kb = servings_keyboard(f"setup_qty:{slot}", ss_index)
        await query.edit_message_text(
            f"*{pending.get('name', '')}* ({unit})\nHow many?",
            reply_markup=kb,
            parse_mode="Markdown",
        )

    elif action == "setup_qty":
        ss_index = int(parts[2])
        amount_str = parts[3]

        if amount_str == "custom":
            context.user_data["setup_pending_custom_qty"] = {"slot": slot, "ss_index": ss_index}
            await query.edit_message_text("Type the amount (e.g. 0.8, 1.5):")
            return

        amount = float(amount_str)
        await query.edit_message_text("...")
        await _save_food_with_serving(update, context, slot, ss_index, amount)

    elif action == "setup_search_again":
        context.user_data["setup_search_slot"] = slot
        await query.edit_message_text(f"Type the food name to search for {MEAL_SLOT_LABELS.get(slot, slot)}:")

    elif action == "setup_next":
        context.user_data.pop("setup_search_slot", None)
        setup["slot_idx"] = setup.get("slot_idx", 0) + 1
        slot_foods = setup.get("foods", {}).get(slot, [])
        if slot_foods:
            names = ", ".join(f["name"] for f in slot_foods)
            await query.edit_message_text(f"{MEAL_SLOT_LABELS.get(slot, slot)}: {names}")
        await _ask_slot(update, context)


async def _save_food_with_serving(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    slot: str, ss_index: int | None, amount: float,
) -> None:
    """Save a food with its serving info to the setup state, then ask for more."""
    setup = context.user_data.get("setup", {})
    pending = context.user_data.pop("setup_pending_food", {})
    if not pending:
        return

    serving_info = {}
    if ss_index is not None:
        ss_list = pending.get("serving_sizes", [])
        ss = next((s for s in ss_list if s.get("index") == ss_index), {})
        serving_info = {
            "serving_size_index": ss_index,
            "servings": amount,
            "unit": ss.get("unit", "serving"),
            "nutrition_multiplier": ss.get("nutrition_multiplier", 1.0),
        }

    foods = setup.setdefault("foods", {})
    slot_foods = foods.setdefault(slot, [])
    slot_foods.append({
        "name": pending["name"],
        "mfp_id": str(pending["mfp_id"]),
        "serving_info": serving_info,
    })

    food_list = ", ".join(f["name"] for f in slot_foods)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Add another food", callback_data=f"setup_search_again:{slot}"),
        InlineKeyboardButton("Done with slot", callback_data=f"setup_next:{slot}"),
    ]])

    unit = serving_info.get("serving_unit", "serving")
    await update.effective_chat.send_message(
        f"Added: {pending['name']} ({amount} {unit})\n"
        f"Current: {food_list}\n\n"
        "Add another food, or move on?",
        reply_markup=kb,
    )


async def _finish_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    setup = context.user_data.pop("setup", {})
    context.user_data.pop("setup_search_slot", None)
    context.user_data.pop("setup_search_results", None)
    context.user_data.pop("setup_pending_food", None)

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    foods_by_slot = setup.get("foods", {})
    total_patterns = 0

    for slot, foods in foods_by_slot.items():
        if not foods:
            continue
        food_names = [f["name"] for f in foods]
        food_ids = [f["mfp_id"] for f in foods]
        # Store per-food serving_info as a list (one entry per food)
        serving_infos = [f.get("serving_info", {}) for f in foods]

        for day_type in ("weekday", "weekend"):
            pattern = MealPattern(
                telegram_user_id=user_id,
                slot=slot,
                day_type=day_type,
                food_combo=json.dumps(food_names),
                mfp_food_ids=json.dumps(food_ids),
                weight=3.0,
                serving_info=json.dumps(serving_infos),
            )
            await save_meal_pattern(db, pattern)
            total_patterns += 1

    slots_filled = len(foods_by_slot)
    await update.effective_chat.send_message(
        f"Setup complete!\n"
        f"{slots_filled} slots configured, {total_patterns} patterns created.\n\n"
        "Try /today to see your predictions!"
    )
