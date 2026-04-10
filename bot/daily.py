from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import (
    alternatives_keyboard,
    search_results_keyboard,
    slot_keyboard_high,
    slot_keyboard_low,
    slot_keyboard_none,
)
from bot.messages import format_day_header, format_day_summary, format_slot_message
from config import MEAL_SLOTS
from db.database import (
    decrypt_password,
    get_meal_entries,
    get_user,
    mark_entry_synced,
    save_meal_entry,
)
from db.models import MealEntry
from engine.learner import on_confirm, on_replace
from engine.predictor import predict_day
from mfp.client import MfpClient

DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _get_target_date(day_name: str) -> date:
    """Get the next occurrence of the given day name."""
    today = date.today()
    target_dow = DAY_NAMES.get(day_name.lower()[:3], -1)
    if target_dow == -1:
        return today
    days_ahead = (target_dow - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 0  # today if it matches
    return today + timedelta(days=days_ahead)


async def _ensure_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> MfpClient | None:
    """Get or create MFP client. Returns None if not logged in."""
    client = context.user_data.get("mfp_client")
    if client:
        return client
    db = context.bot_data["db"]
    user = await get_user(db, update.effective_user.id)
    if not user or not user.onboarding_done:
        await update.message.reply_text("Please /start first to set up your account.")
        return None
    password = decrypt_password(user.mfp_password_encrypted)
    client = MfpClient(user.mfp_username, password)
    await client.login()
    context.user_data["mfp_client"] = client
    return client


async def _send_slot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_date: date,
    slot: str,
    prediction: dict,
    day_index: int | None = None,
    total_days: int | None = None,
) -> None:
    """Send a single slot message with appropriate keyboard."""
    text = format_slot_message(slot, prediction)

    if prediction["confidence"] == "high":
        kb = slot_keyboard_high(slot, prediction["top"]["pattern_id"])
    elif prediction["confidence"] == "low":
        kb = slot_keyboard_low(slot, prediction["alternatives"])
    else:
        kb = slot_keyboard_none(slot)

    # Store context for callback handlers
    context.user_data.setdefault("current_day", {})
    context.user_data["current_day"]["date"] = target_date.isoformat()
    context.user_data["current_day"]["predictions"] = context.user_data.get("current_day", {}).get("predictions", {})
    context.user_data["current_day"]["predictions"][slot] = prediction
    context.user_data["current_day"]["current_slot_idx"] = MEAL_SLOTS.index(slot)

    await update.effective_chat.send_message(text, reply_markup=kb, parse_mode="Markdown")


async def _send_next_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Send the next pending slot. Returns True if there was a slot to send, False if day is complete."""
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    day_data = context.user_data.get("current_day", {})
    target_date = date.fromisoformat(day_data["date"])
    predictions = day_data.get("all_predictions", {})

    current_idx = day_data.get("current_slot_idx", -1) + 1

    # Find next slot that hasn't been filled
    while current_idx < len(MEAL_SLOTS):
        slot = MEAL_SLOTS[current_idx]
        existing = await get_meal_entries(db, user_id, target_date.isoformat(), slot)
        if not existing:
            context.user_data["current_day"]["current_slot_idx"] = current_idx
            await _send_slot(update, context, target_date, slot, predictions[slot])
            return True
        current_idx += 1

    return False


async def start_day_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_date: date,
    day_index: int | None = None,
    total_days: int | None = None,
) -> None:
    """Start the slot-by-slot flow for a single day."""
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    predictions = await predict_day(db, user_id, target_date)

    # Store all predictions for this day
    context.user_data["current_day"] = {
        "date": target_date.isoformat(),
        "all_predictions": predictions,
        "predictions": {},
        "current_slot_idx": -1,
        "confirmed": 0,
        "skipped": 0,
        "day_index": day_index,
        "total_days": total_days,
    }

    header = format_day_header(target_date.isoformat(), day_index, total_days)
    await update.effective_chat.send_message(header, parse_mode="Markdown")

    has_slot = await _send_next_slot(update, context)
    if not has_slot:
        await update.effective_chat.send_message(
            f"\u2705 All slots already filled for {target_date.isoformat()}!"
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    await start_day_flow(update, context, date.today())


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    await start_day_flow(update, context, date.today() + timedelta(days=1))


async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await _ensure_client(update, context)
    if not client:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/day Mon`", parse_mode="Markdown")
        return
    target = _get_target_date(context.args[0])
    await start_day_flow(update, context, target)


async def slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirm/change/skip/pick/search callbacks for slots."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    data = query.data
    parts = data.split(":")
    action = parts[0]
    slot = parts[1] if len(parts) > 1 else ""

    day_data = context.user_data.get("current_day", {})
    target_date = day_data.get("date", date.today().isoformat())
    predictions = day_data.get("all_predictions", {})
    prediction = predictions.get(slot, {})

    if action == "confirm":
        pattern_id = int(parts[2])
        foods = prediction.get("top", {}).get("foods", [])
        mfp_ids = prediction.get("top", {}).get("mfp_ids", [])

        # Save to history
        parsed_date = date.fromisoformat(target_date)
        for food, mfp_id in zip(foods, mfp_ids):
            entry = MealEntry(
                telegram_user_id=user_id,
                date=target_date,
                day_of_week=parsed_date.weekday(),
                slot=slot,
                food_name=food,
                quantity="",
                mfp_food_id=str(mfp_id),
                source="bot_confirm",
                synced_to_mfp=False,
            )
            entry_id = await save_meal_entry(db, entry)

            # Try to sync to MFP
            client = context.user_data.get("mfp_client")
            if client:
                try:
                    await client.add_entry(target_date, slot, food, str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass  # stays unsynced, user can /retry later

        await on_confirm(db, pattern_id, target_date)

        day_data["confirmed"] = day_data.get("confirmed", 0) + 1
        await query.edit_message_text(f"\u2705 {', '.join(foods)} logged!")

        # Send next slot
        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            # If in week mode, trigger next day
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "pick":
        pattern_id = int(parts[2])
        # Find the picked alternative
        alts = prediction.get("alternatives", [])
        picked = next((a for a in alts if a["pattern_id"] == pattern_id), None)
        if not picked:
            return

        parsed_date = date.fromisoformat(target_date)
        for food, mfp_id in zip(picked["foods"], picked["mfp_ids"]):
            entry = MealEntry(
                telegram_user_id=user_id,
                date=target_date,
                day_of_week=parsed_date.weekday(),
                slot=slot,
                food_name=food,
                quantity="",
                mfp_food_id=str(mfp_id),
                source="bot_confirm",
                synced_to_mfp=False,
            )
            entry_id = await save_meal_entry(db, entry)
            client = context.user_data.get("mfp_client")
            if client:
                try:
                    await client.add_entry(target_date, slot, food, str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass

        day_type = "weekend" if parsed_date.weekday() >= 5 else "weekday"
        await on_replace(db, user_id, slot, day_type, picked["foods"], picked["mfp_ids"], target_date)

        day_data["confirmed"] = day_data.get("confirmed", 0) + 1
        await query.edit_message_text(f"\u2705 {', '.join(picked['foods'])} logged!")

        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "change":
        # Show alternatives
        alts = prediction.get("alternatives", [])
        if not alts:
            # Fetch from DB
            from db.database import get_meal_patterns
            day_type = "weekend" if date.fromisoformat(target_date).weekday() >= 5 else "weekday"
            patterns = await get_meal_patterns(db, user_id, slot, day_type)
            alts = [
                {"foods": p.get_food_combo_list(), "mfp_ids": p.get_mfp_food_ids_list(), "pattern_id": p.id}
                for p in patterns[:5]
            ]
        kb = alternatives_keyboard(slot, alts)
        await query.edit_message_text(f"Alternatives for {slot}:", reply_markup=kb)

    elif action == "skip":
        day_data["skipped"] = day_data.get("skipped", 0) + 1
        await query.edit_message_text(f"\u23ED {slot} skipped")

        has_next = await _send_next_slot(update, context)
        if not has_next:
            summary = format_day_summary(
                target_date, day_data.get("confirmed", 0), day_data["skipped"], len(MEAL_SLOTS)
            )
            await update.effective_chat.send_message(summary)
            if "week_mode" in context.user_data:
                from bot.week import advance_week
                await advance_week(update, context)

    elif action == "search":
        context.user_data["search_slot"] = slot
        await query.edit_message_text(f"Type the food name to search for {slot}:")

    elif action == "search_pick":
        mfp_id = parts[2]
        # Look up food details
        client = context.user_data.get("mfp_client")
        if client:
            details = await client.get_food_details(int(mfp_id))
            if details:
                parsed_date = date.fromisoformat(target_date)
                entry = MealEntry(
                    telegram_user_id=user_id,
                    date=target_date,
                    day_of_week=parsed_date.weekday(),
                    slot=slot,
                    food_name=details["name"],
                    quantity="",
                    mfp_food_id=str(mfp_id),
                    source="bot_search",
                    synced_to_mfp=False,
                )
                entry_id = await save_meal_entry(db, entry)
                try:
                    await client.add_entry(target_date, slot, details["name"], str(mfp_id))
                    await mark_entry_synced(db, entry_id)
                except Exception:
                    pass

                day_type = "weekend" if parsed_date.weekday() >= 5 else "weekday"
                await on_replace(db, user_id, slot, day_type, [details["name"]], [str(mfp_id)], target_date)

                day_data["confirmed"] = day_data.get("confirmed", 0) + 1
                await query.edit_message_text(f"\u2705 {details['name']} logged!")

                has_next = await _send_next_slot(update, context)
                if not has_next:
                    summary = format_day_summary(
                        target_date, day_data["confirmed"], day_data.get("skipped", 0), len(MEAL_SLOTS)
                    )
                    await update.effective_chat.send_message(summary)
                    if "week_mode" in context.user_data:
                        from bot.week import advance_week
                        await advance_week(update, context)

    elif action == "back":
        # Re-send original slot
        await _send_slot(update, context, date.fromisoformat(target_date), slot, prediction)
        try:
            await query.message.delete()
        except Exception:
            pass


async def search_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text search when user is in search mode."""
    search_slot = context.user_data.get("search_slot")
    if not search_slot:
        return  # not in search mode

    client = context.user_data.get("mfp_client")
    if not client:
        await update.message.reply_text("Not connected to MFP. Please /login first.")
        return

    query_text = update.message.text.strip()
    results = await client.search_food(query_text)

    if not results:
        await update.message.reply_text(f"No results for '{query_text}'. Try again:")
        return

    kb = search_results_keyboard(search_slot, results)
    await update.message.reply_text(f"Results for '{query_text}':", reply_markup=kb)
    context.user_data.pop("search_slot", None)
