from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.messages import format_status_line
from config import MEAL_SLOT_EMOJIS, MEAL_SLOTS
from db.database import (
    decrypt_password,
    get_meal_entries,
    get_unsynced_entries,
    get_user,
)
from mfp.client import MfpClient
from mfp.sync import retry_unsynced


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client, _fetch_mfp_filled_slots

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()
    client = await _ensure_client(update, context)

    if not client:
        return

    lines = ["\U0001F4CB *Weekly Status*\n"]

    for i in range(7):
        d = today + timedelta(days=i)
        logged = 0
        try:
            filled = await _fetch_mfp_filled_slots(client, d)
            logged = len(filled)
        except Exception:
            pass

        pending = len(MEAL_SLOTS) - logged
        lines.append(format_status_line(d.isoformat(), logged, pending))

    unsynced = await get_unsynced_entries(db, user_id)
    if unsynced:
        lines.append(f"\n\u26A0 _{len(unsynced)} entries not synced._ Use /pending")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client

    client = await _ensure_client(update, context)
    if not client:
        return

    today = date.today()
    try:
        entries = await client.get_recent_entries(today)
    except Exception:
        await update.message.reply_text("\u26A0 Could not reach MFP. Try again later.")
        return

    if not entries:
        await update.message.reply_text("\u2049 Nothing to undo for today.")
        return

    latest = entries[0]
    try:
        await client.delete_entry(latest["uuid"])
    except Exception:
        await update.message.reply_text("\u26A0 Failed to delete from MFP. Try again later.")
        return

    # Also remove from local DB if present
    db = context.bot_data["db"]
    user_id = update.effective_user.id
    await db.execute(
        "DELETE FROM meals_history WHERE id = ("
        "  SELECT id FROM meals_history"
        "  WHERE telegram_user_id = ? AND date = ? AND food_name = ?"
        "  ORDER BY id DESC LIMIT 1"
        ")",
        (user_id, today.isoformat(), latest["food_name"]),
    )
    await db.commit()

    emoji = MEAL_SLOT_EMOJIS.get(latest["slot"], "")
    await update.message.reply_text(
        f"\u21A9 *Removed from MFP:* {latest['food_name']}\n"
        f"{emoji} {latest['meal_name']}",
        parse_mode="Markdown",
    )


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    client = context.user_data.get("mfp_client")
    if not client:
        user = await get_user(db, user_id)
        if not user:
            await update.message.reply_text("Please /start first.")
            return
        token_json = decrypt_password(user.mfp_password_encrypted)
        client = MfpClient.from_auth_json(token_json)
        context.user_data["mfp_client"] = client

    msg = await update.message.reply_text("\U0001F504 Retrying unsynced entries...")
    synced, failed, errors = await retry_unsynced(db, client, user_id)

    if failed:
        error_lines = "\n".join(f"  • {e}" for e in errors[:5])
        await msg.edit_text(
            f"\u26A0 Retry: *{synced}* synced, *{failed}* failed.\n\n{error_lines}",
            parse_mode="Markdown",
        )
    elif synced:
        await msg.edit_text(f"\u2705 All *{synced}* entries synced!", parse_mode="Markdown")
    else:
        await msg.edit_text("\u2705 Nothing to retry — all synced.")


async def macros_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client
    from bot.messages import format_macro_summary

    client = await _ensure_client(update, context)
    if not client:
        return

    goals = context.user_data.get("macro_goals")
    if not goals:
        goals = await client.get_nutrient_goals()
        if goals:
            context.user_data["macro_goals"] = goals

    if not goals:
        await update.message.reply_text("Could not fetch your macro goals from MFP.")
        return

    totals = await client.get_day_totals(date.today())
    summary = format_macro_summary(totals, goals)
    await update.message.reply_text(summary or "No data for today yet.", parse_mode="Markdown")


async def copy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client, _get_target_date, _send_macro_update, DAY_NAMES

    client = await _ensure_client(update, context)
    if not client:
        return

    if not context.args:
        await update.message.reply_text("Usage: `/copy yesterday` or `/copy monday`", parse_mode="Markdown")
        return

    arg = context.args[0].lower()
    today = date.today()

    if arg == "yesterday":
        source_date = today - timedelta(days=1)
    elif arg[:3] in DAY_NAMES:
        source_date = _get_target_date(arg)
        if source_date >= today:
            source_date -= timedelta(days=7)
    else:
        try:
            source_date = date.fromisoformat(arg)
        except ValueError:
            await update.message.reply_text(
                "Usage: `/copy yesterday`, `/copy monday`, or `/copy 2026-04-12`",
                parse_mode="Markdown",
            )
            return

    db = context.bot_data["db"]
    user_id = update.effective_user.id

    source_entries = await get_meal_entries(db, user_id, source_date.isoformat())
    if not source_entries:
        await update.message.reply_text(f"No meals found for {source_date.isoformat()}.")
        return

    msg = await update.message.reply_text(f"Copying from {source_date.isoformat()}...")

    from db.database import mark_entry_synced, save_meal_entry
    from db.models import MealEntry

    copied = 0
    failed_syncs = 0
    skipped_slots = []
    slot_foods: dict[str, list[str]] = {}

    # Pre-check which slots are already filled today (check once per slot)
    already_filled: set[str] = set()
    for entry in source_entries:
        if entry.slot not in already_filled:
            existing = await get_meal_entries(db, user_id, today.isoformat(), entry.slot)
            if existing:
                already_filled.add(entry.slot)

    for entry in source_entries:
        if entry.slot in already_filled:
            if entry.slot not in skipped_slots:
                skipped_slots.append(entry.slot)
            continue

        new_entry = MealEntry(
            telegram_user_id=user_id,
            date=today.isoformat(),
            day_of_week=today.weekday(),
            slot=entry.slot,
            food_name=entry.food_name,
            quantity=entry.quantity,
            mfp_food_id=entry.mfp_food_id,
            serving_info=entry.serving_info,
            source="bot_confirm",
            synced_to_mfp=False,
        )
        entry_id = await save_meal_entry(db, new_entry)

        if client and entry.mfp_food_id and entry.mfp_food_id not in ("", "None"):
            try:
                serving_info = {}
                if entry.serving_info and entry.serving_info != "{}":
                    import json
                    try:
                        serving_info = json.loads(entry.serving_info)
                    except json.JSONDecodeError:
                        serving_info = {}
                await client.add_entry(
                    today.isoformat(),
                    entry.slot,
                    entry.food_name,
                    entry.mfp_food_id,
                    servings=serving_info.get("servings", 1.0),
                    serving_size_index=serving_info.get("serving_size_index"),
                    fallback_serving=serving_info,
                )
                await mark_entry_synced(db, entry_id)
            except Exception:
                failed_syncs += 1

        slot_foods.setdefault(entry.slot, []).append(entry.food_name)
        copied += 1

    lines = [f"Copied {copied} entries from {source_date.isoformat()}:"]
    for slot, foods in slot_foods.items():
        lines.append(f"  {slot}: {', '.join(foods)}")
    if skipped_slots:
        lines.append(f"  Skipped (already filled): {', '.join(skipped_slots)}")
    if failed_syncs:
        lines.append(f"  Saved locally only: {failed_syncs} entries failed MFP sync. Use /retry")

    await msg.edit_text("\n".join(lines))
    if not failed_syncs:
        await _send_macro_update(update, context, today)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client
    from bot.messages import format_history

    client = await _ensure_client(update, context)
    if not client:
        return

    goals = context.user_data.get("macro_goals")
    if not goals:
        goals = await client.get_nutrient_goals()
        if goals:
            context.user_data["macro_goals"] = goals

    msg = await update.message.reply_text("\U0001F4C8 Loading 7-day history...")

    today = date.today()
    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        totals = await client.get_day_totals(d)
        days.append({"date": d.isoformat(), "totals": totals})

    text = format_history(days, goals or {})
    await msg.edit_text(text, parse_mode="Markdown")


async def patterns_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _clean_food_name
    from config import MEAL_SLOT_LABELS
    from db.database import get_meal_patterns

    db = context.bot_data["db"]
    user_id = update.effective_user.id
    today = date.today()
    day_type = "weekend" if today.weekday() >= 5 else "weekday"

    lines = [f"\U0001F4D6 *Your patterns* ({day_type})\n"]
    total = 0

    for slot in MEAL_SLOTS:
        emoji = MEAL_SLOT_EMOJIS.get(slot, "")
        label = MEAL_SLOT_LABELS.get(slot, slot)
        patterns = await get_meal_patterns(db, user_id, slot, day_type)

        if not patterns:
            lines.append(f"{emoji} *{label}*  _no patterns yet_\n")
            continue

        total_weight = sum(p.weight for p in patterns)
        lines.append(f"{emoji} *{label}*  _{len(patterns)} patterns_")

        medals = ["\U0001F947", "\U0001F948", "\U0001F949"]
        shown = 0
        for i, p in enumerate(patterns):
            pct = p.weight / total_weight * 100 if total_weight > 0 else 0
            if pct < 2 and i >= 3:
                break
            if shown >= 5:
                break

            foods = [_clean_food_name(f) for f in p.get_food_combo_list()]
            medal = medals[i] if i < 3 else "  "

            # Show up to 3 foods, then "+N"
            if len(foods) <= 3:
                food_str = ", ".join(foods)
            else:
                food_str = ", ".join(foods[:3]) + f" +{len(foods) - 3}"

            lines.append(f"  {medal} {food_str}  _{pct:.0f}%_")
            shown += 1
            total += 1

        remaining = len(patterns) - shown
        if remaining > 0:
            lines.append(f"  _...+{remaining} more_")
        lines.append("")

    if total == 0:
        lines.append("_No patterns yet. Use /import or /today to start building them._")

    # Telegram messages max 4096 chars
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    entries = await get_unsynced_entries(db, user_id)
    if not entries:
        await update.message.reply_text("\u2705 All synced! Nothing pending.")
        return

    lines = [f"\u23F3 *{len(entries)} pending entries:*\n"]
    for e in entries[:15]:
        emoji = MEAL_SLOT_EMOJIS.get(e.slot, "")
        lines.append(f"  {emoji} {e.date} {e.slot}: {e.food_name}")

    if len(entries) > 15:
        lines.append(f"\n  _...+{len(entries) - 15} more_")

    lines.append("\nUse /retry to sync, or /reset to clear all local data.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    args = context.args or []
    if not args or args[0].lower() != "confirm":
        await update.message.reply_text(
            "\u26A0 *Factory Reset*\n\n"
            "This will delete all your local data:\n"
            "  \u2022 Meal history\n"
            "  \u2022 Patterns\n"
            "  \u2022 Week progress\n\n"
            "Your MFP diary is NOT affected.\n\n"
            "Type `/reset confirm` to proceed.",
            parse_mode="Markdown",
        )
        return

    await db.execute("DELETE FROM meals_history WHERE telegram_user_id = ?", (user_id,))
    await db.execute("DELETE FROM meal_patterns WHERE telegram_user_id = ?", (user_id,))
    await db.execute("DELETE FROM week_progress WHERE telegram_user_id = ?", (user_id,))
    await db.commit()

    await update.message.reply_text(
        "\u2705 Reset complete. All local data cleared.\n\n"
        "Use /import to re-import your MFP history."
    )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from engine.pattern_analyzer import analyze_history

    db = context.bot_data["db"]
    user_id = update.effective_user.id

    msg = await update.message.reply_text("\U0001F50D Analyzing your meal history...")
    pattern_count = await analyze_history(db, user_id)
    await msg.edit_text(
        f"\u2705 Analysis complete!\n"
        f"*{pattern_count}* patterns found.\n\n"
        "Use /patterns to see them, or /today to get predictions.",
        parse_mode="Markdown",
    )
