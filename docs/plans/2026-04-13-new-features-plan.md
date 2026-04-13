# New Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 features to MFP Auto Bot: serving sizes in patterns, evening reminders, `/macros`, `/suggest`, `/copy`, `/history`.

**Architecture:** Each feature is largely independent. Tasks 1-2 modify the data layer and client (shared foundation). Tasks 3-8 add features that can be built in any order after the foundation. Each task includes tests first (TDD).

**Tech Stack:** Python 3.14, python-telegram-bot 22.7, aiosqlite, curl_cffi, pytest/pytest-asyncio

---

### Task 1: Add serving_info to data layer

**Files:**
- Modify: `db/models.py`
- Modify: `db/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write failing test for serving_info in MealPattern**

Add to `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_meal_pattern_serving_info(db):
    from db.database import save_user, save_meal_pattern, get_meal_patterns
    from db.models import User, MealPattern
    import json

    user = User(telegram_user_id=99999, mfp_username="u", mfp_password_encrypted="e")
    await save_user(db, user)

    pattern = MealPattern(
        telegram_user_id=99999,
        slot="breakfast",
        day_type="weekday",
        food_combo='["Oatmeal"]',
        mfp_food_ids='["111"]',
        weight=3.0,
        serving_info=json.dumps({"serving_size_index": 4, "servings": 0.8, "serving_unit": "g", "nutrition_multiplier": 1.0}),
    )
    await save_meal_pattern(db, pattern)

    patterns = await get_meal_patterns(db, 99999, "breakfast", "weekday")
    assert len(patterns) == 1
    info = json.loads(patterns[0].serving_info)
    assert info["servings"] == 0.8
    assert info["serving_unit"] == "g"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_meal_pattern_serving_info -v`
Expected: FAIL — `MealPattern.__init__() got an unexpected keyword argument 'serving_info'`

- [ ] **Step 3: Add serving_info to MealPattern dataclass**

In `db/models.py`, add to `MealPattern` (after `updated_at`):

```python
    serving_info: str = "{}"
```

- [ ] **Step 4: Add serving_info column to DB schema and CRUD**

In `db/database.py`, modify the `meal_patterns` CREATE TABLE to add:
```sql
    serving_info TEXT NOT NULL DEFAULT '{}',
```
(Add it after the `updated_at` column line.)

In `save_meal_pattern()`, add `serving_info` to the INSERT:
```python
async def save_meal_pattern(db: aiosqlite.Connection, pattern: MealPattern) -> int:
    cursor = await db.execute(
        """INSERT INTO meal_patterns
           (telegram_user_id, slot, day_type, food_combo, mfp_food_ids, weight, last_confirmed, updated_at, serving_info)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pattern.telegram_user_id, pattern.slot, pattern.day_type, pattern.food_combo,
         pattern.mfp_food_ids, pattern.weight, pattern.last_confirmed, pattern.updated_at, pattern.serving_info),
    )
    await db.commit()
    return cursor.lastrowid
```

In `get_meal_patterns()`, add `serving_info` to the row mapping:
```python
            patterns.append(MealPattern(
                id=row["id"],
                telegram_user_id=row["telegram_user_id"],
                slot=row["slot"],
                day_type=row["day_type"],
                food_combo=row["food_combo"],
                mfp_food_ids=row["mfp_food_ids"],
                weight=row["weight"],
                last_confirmed=row["last_confirmed"],
                updated_at=row["updated_at"],
                serving_info=row["serving_info"],
            ))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_database.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add db/models.py db/database.py tests/test_database.py
git commit -m "feat: add serving_info to MealPattern for portion tracking"
```

---

### Task 2: Enrich search results with serving_sizes and nutritional_contents

**Files:**
- Modify: `mfp/client.py`
- Test: `tests/test_mfp_client.py`

- [ ] **Step 1: Write failing test for enriched search results**

Add to `tests/test_mfp_client.py`:

```python
def test_search_food_returns_serving_sizes(client):
    api_response = {
        "items": [
            {
                "item": {
                    "id": "123",
                    "description": "Oatmeal",
                    "serving_sizes": [
                        {"index": 0, "value": 1.0, "unit": "cup", "nutrition_multiplier": 1.0},
                        {"index": 1, "value": 100.0, "unit": "g", "nutrition_multiplier": 0.83},
                    ],
                    "nutritional_contents": {
                        "energy": {"value": 150, "unit": "calories"},
                        "protein": 5.0,
                        "carbohydrates": 27.0,
                        "fat": 3.0,
                    },
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status = MagicMock()
    client.session.get = MagicMock(return_value=mock_resp)

    results = client.search_food_sync("oatmeal")
    assert len(results) == 1
    assert results[0]["name"] == "Oatmeal"
    assert len(results[0]["serving_sizes"]) == 2
    assert results[0]["serving_sizes"][0]["unit"] == "cup"
    assert results[0]["nutrition"]["protein"] == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mfp_client.py::test_search_food_returns_serving_sizes -v`
Expected: FAIL — `KeyError: 'serving_sizes'`

- [ ] **Step 3: Enrich search_food_sync to include serving_sizes and nutrition**

In `mfp/client.py`, modify `search_food_sync`:

```python
    def search_food_sync(self, query: str) -> list[dict]:
        """Search MFP food database. Returns list with name, mfp_id, serving_sizes, nutrition."""
        data = self._api_get("v2/nutrition", [
            ("q", query),
            ("fields[]", "nutritional_contents"),
            ("fields[]", "name"),
            ("fields[]", "brand_name"),
            ("fields[]", "serving_sizes"),
        ])
        results = []
        for wrapper in data.get("items", []):
            inner = wrapper.get("item", wrapper)
            name = (
                inner.get("description", "")
                or inner.get("name", "")
                or inner.get("brand_name", "")
            )
            mfp_id = inner.get("id")
            if name:
                nc = inner.get("nutritional_contents", {})
                energy = nc.get("energy", {})
                results.append({
                    "name": name,
                    "mfp_id": mfp_id,
                    "serving_sizes": inner.get("serving_sizes", []),
                    "nutrition": {
                        "calories": energy.get("value", 0) if isinstance(energy, dict) else 0,
                        "protein": nc.get("protein", 0),
                        "carbs": nc.get("carbohydrates", 0),
                        "fat": nc.get("fat", 0),
                    },
                    "version": str(inner.get("version", mfp_id)),
                })
        return results
```

- [ ] **Step 4: Update add_entry_sync to accept serving parameters**

In `mfp/client.py`, modify `add_entry_sync` signature and body:

```python
    def add_entry_sync(
        self,
        date_str: str,
        meal_name: str,
        food_name: str,
        mfp_food_id: str,
        servings: float = 1.0,
        serving_size_index: int | None = None,
    ) -> bool:
        """Add a food entry to the MFP diary. Raises on failure."""
        if not mfp_food_id or mfp_food_id in ("None", ""):
            raise ValueError(f"No food ID for '{food_name}' — cannot sync to MFP")

        info = self._lookup_food_sync(food_name, mfp_food_id)
        version = info["version"]
        serving_sizes = info["serving_sizes"]

        # Pick serving_size by index, or first available
        ss = None
        if serving_sizes:
            if serving_size_index is not None:
                ss = next((s for s in serving_sizes if s.get("index") == serving_size_index), None)
            if ss is None:
                ss = serving_sizes[0]

        if ss:
            serving_size = {
                "value": ss.get("value", 1.0),
                "unit": ss.get("unit", "serving"),
                "nutrition_multiplier": ss.get("nutrition_multiplier", 1.0),
            }
        else:
            serving_size = {"value": 1.0, "unit": "serving", "nutrition_multiplier": 1.0}

        meal_position = _SLOT_TO_MEAL_POSITION.get(meal_name, 3)

        payload = {
            "items": [
                {
                    "type": "food_entry",
                    "date": date_str,
                    "meal_position": meal_position,
                    "food": {
                        "id": str(mfp_food_id),
                        "version": version,
                    },
                    "servings": servings,
                    "serving_size": serving_size,
                }
            ]
        }

        self._api_post("v2/diary", payload)
        logger.info("Added '%s' to MFP diary (%s, %s)", food_name, date_str, meal_name)
        return True
```

Update the async wrapper too:

```python
    async def add_entry(self, date_str: str, meal_name: str, food_name: str, mfp_food_id: str,
                        servings: float = 1.0, serving_size_index: int | None = None) -> bool:
        return await asyncio.to_thread(self.add_entry_sync, date_str, meal_name, food_name, mfp_food_id,
                                       servings, serving_size_index)
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_mfp_client.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add mfp/client.py tests/test_mfp_client.py
git commit -m "feat: enrich search with serving_sizes and nutrition, add serving params to add_entry"
```

---

### Task 3: Serving size selection in setup and daily flow

**Files:**
- Modify: `bot/setup.py`
- Modify: `bot/daily.py`
- Modify: `bot/keyboards.py`

- [ ] **Step 1: Add serving_size and quantity keyboards to `bot/keyboards.py`**

Add at the end of `bot/keyboards.py`:

```python
def serving_size_keyboard(callback_prefix: str, serving_sizes: list[dict]) -> InlineKeyboardMarkup:
    """Show serving_size options as buttons. callback_prefix is e.g. 'setup_ss' or 'ss'."""
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
```

- [ ] **Step 2: Wire serving selection into setup wizard**

In `bot/setup.py`, after `setup_pick` saves the food, instead of immediately adding to slot_foods, show serving_size keyboard. Add new callback handlers `setup_ss` (pick serving_size) and `setup_qty` (pick quantity). After quantity is confirmed, save the food with its serving_info to setup state and then to the pattern in `_finish_setup`.

Update `setup_callback` to handle new actions:
- `setup_ss:{slot}:{ss_index}` — user picked a serving_size, show quantity buttons
- `setup_qty:{slot}:{ss_index}:{amount}` — user picked quantity, save food with serving info
- `setup_qty:{slot}:{ss_index}:custom` — set a flag, wait for free-text number

Update `_finish_setup` to include `serving_info` when creating MealPattern.

The full implementation: after `setup_pick`, store the food in `context.user_data["setup_pending_food"]` and show `serving_size_keyboard("setup_ss:{slot}")`. On `setup_ss`, show `servings_keyboard("setup_qty:{slot}")`. On `setup_qty`, calculate serving_info JSON and add to slot_foods, then ask for more or next slot.

- [ ] **Step 3: Wire serving info into daily confirm flow**

In `bot/daily.py`, when action is `"confirm"`:
- Read `serving_info` from the pattern's `serving_info` field
- Pass `servings` and `serving_size_index` to `client.add_entry()`

```python
        # In the confirm action, after getting pattern_id:
        import json as _json
        pattern_serving = {}
        for p in day_data.get("all_predictions", {}).get(slot, {}).get("alternatives", []):
            if p.get("pattern_id") == pattern_id:
                pattern_serving = p.get("serving_info", {})
                break
        if not pattern_serving:
            top = prediction.get("top", {})
            pattern_serving = top.get("serving_info", {})

        servings_val = pattern_serving.get("servings", 1.0)
        ss_index = pattern_serving.get("serving_size_index")
```

Then pass these to `client.add_entry()`:
```python
        await client.add_entry(target_date, slot, food, str(mfp_id),
                               servings=servings_val, serving_size_index=ss_index)
```

- [ ] **Step 4: Update predictor to include serving_info in predictions**

In `engine/predictor.py`, include `serving_info` in the top and alternatives dicts:

```python
        top_entry = {
            "foods": top.get_food_combo_list(),
            "mfp_ids": top.get_mfp_food_ids_list(),
            "pattern_id": top.id,
            "serving_info": json.loads(top.serving_info),
        }

        alternatives = [
            {
                "foods": p.get_food_combo_list(),
                "mfp_ids": p.get_mfp_food_ids_list(),
                "pattern_id": p.id,
                "serving_info": json.loads(p.serving_info),
            }
            for p in patterns[:MAX_ALTERNATIVES]
        ]
```

Add `import json` at top of predictor.py.

- [ ] **Step 5: Run all tests, fix any breakages**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/setup.py bot/daily.py bot/keyboards.py engine/predictor.py
git commit -m "feat: serving size selection in setup and daily flow"
```

---

### Task 4: Evening reminder

**Files:**
- Create: `bot/reminder.py`
- Modify: `config.py`
- Modify: `main.py`
- Test: `tests/test_reminder.py`

- [ ] **Step 1: Add REMINDER_HOUR to config.py**

In `config.py`, add at the end:

```python
REMINDER_HOUR: int = 21  # 24h format, local time (Italy)
```

- [ ] **Step 2: Write test for reminder logic**

Create `tests/test_reminder.py`:

```python
import pytest
import pytest_asyncio
import aiosqlite
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from db.database import init_db, save_user, save_meal_entry
from db.models import User, MealEntry


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_check_user_returns_empty_slot_count(db):
    from bot.reminder import _count_empty_slots

    user = User(telegram_user_id=12345, mfp_username="u", mfp_password_encrypted="e", onboarding_done=True)
    await save_user(db, user)

    # No entries at all → 7 empty slots
    count = await _count_empty_slots(db, 12345, date.today())
    assert count == 7

    # Add one entry → 6 empty
    entry = MealEntry(telegram_user_id=12345, date=date.today().isoformat(), day_of_week=0,
                      slot="breakfast", food_name="Oats", quantity="80g")
    await save_meal_entry(db, entry)
    count = await _count_empty_slots(db, 12345, date.today())
    assert count == 6
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_reminder.py -v`
Expected: FAIL — `cannot import name '_count_empty_slots' from 'bot.reminder'`

- [ ] **Step 4: Implement bot/reminder.py**

Create `bot/reminder.py`:

```python
from __future__ import annotations

import logging
from datetime import date, time

from telegram.ext import Application, ContextTypes

from config import MEAL_SLOTS, REMINDER_HOUR
from db.database import get_meal_entries

logger = logging.getLogger(__name__)


async def _count_empty_slots(db, telegram_user_id: int, target_date: date) -> int:
    """Count how many meal slots have no entries for the given date."""
    empty = 0
    for slot in MEAL_SLOTS:
        entries = await get_meal_entries(db, telegram_user_id, target_date.isoformat(), slot)
        if not entries:
            empty += 1
    return empty


async def _check_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: check all users for empty slots and send reminders."""
    db = context.application.bot_data.get("db")
    if not db:
        return

    today = date.today()

    import aiosqlite
    async with db.execute(
        "SELECT telegram_user_id FROM users WHERE onboarding_done = 1"
    ) as cursor:
        users = [row["telegram_user_id"] async for row in cursor]

    for user_id in users:
        try:
            empty = await _count_empty_slots(db, user_id, today)
            if empty > 0:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"You have {empty} meal slots not logged today. Use /today to fill them.",
                )
        except Exception:
            logger.debug("Reminder failed for user %s", user_id, exc_info=True)


def schedule_reminders(application: Application) -> None:
    """Schedule the daily reminder job."""
    application.job_queue.run_daily(
        _check_daily,
        time=time(hour=REMINDER_HOUR, minute=0),
        name="daily_reminder",
    )
```

- [ ] **Step 5: Wire into main.py**

In `main.py`, at the end of `post_init`, add:

```python
    from bot.reminder import schedule_reminders
    schedule_reminders(application)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_reminder.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/reminder.py config.py main.py tests/test_reminder.py
git commit -m "feat: evening reminder for unfilled meal slots"
```

---

### Task 5: `/macros` command

**Files:**
- Modify: `bot/utility.py`
- Modify: `main.py`

- [ ] **Step 1: Implement macros_command in bot/utility.py**

Add to `bot/utility.py`:

```python
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
    await update.message.reply_text(summary or "No data for today yet.")
```

- [ ] **Step 2: Register in main.py**

Add import: `from bot.utility import macros_command` (add to existing import line).
Add handler: `application.add_handler(CommandHandler("macros", macros_command))`.

- [ ] **Step 3: Run all tests**

Run: `pytest -v --ignore=tests/test_integration_telegram.py`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add bot/utility.py main.py
git commit -m "feat: /macros command shows remaining daily macros"
```

---

### Task 6: `/suggest` command

**Files:**
- Create: `bot/suggest.py`
- Modify: `main.py`
- Test: `tests/test_suggest.py`

- [ ] **Step 1: Write test for suggest logic**

Create `tests/test_suggest.py`:

```python
import pytest
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
    assert "Pizza" not in names  # exceeds calories, carbs, fat


def test_filter_suggestions_sorted_by_protein():
    remaining = {"calories": 1000, "protein": 100, "carbs": 200, "fat": 50}
    foods = [
        {"name": "Rice", "nutrition": {"calories": 200, "protein": 4, "carbs": 45, "fat": 0}},
        {"name": "Chicken", "nutrition": {"calories": 250, "protein": 46, "carbs": 0, "fat": 5}},
    ]
    result = _filter_suggestions(foods, remaining)
    assert result[0]["name"] == "Chicken"  # higher protein first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_suggest.py -v`
Expected: FAIL — `cannot import name '_filter_suggestions'`

- [ ] **Step 3: Implement bot/suggest.py**

Create `bot/suggest.py`:

```python
from __future__ import annotations

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from db.database import get_meal_patterns


def _filter_suggestions(foods: list[dict], remaining: dict) -> list[dict]:
    """Filter foods that fit within remaining macro budget, sorted by protein desc."""
    fits = []
    for f in foods:
        n = f.get("nutrition", {})
        if (n.get("calories", 0) <= remaining.get("calories", 0)
                and n.get("protein", 0) <= remaining.get("protein", 0) + 5  # small tolerance
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

    # Get all user patterns
    db = context.bot_data["db"]
    user_id = update.effective_user.id

    all_foods: dict[str, dict] = {}  # mfp_id -> {name, nutrition}
    for day_type in ("weekday", "weekend"):
        from config import MEAL_SLOTS
        for slot in MEAL_SLOTS:
            patterns = await get_meal_patterns(db, user_id, slot, day_type)
            for p in patterns:
                for food_name, mfp_id in zip(p.get_food_combo_list(), p.get_mfp_food_ids_list()):
                    if mfp_id and mfp_id not in all_foods:
                        all_foods[mfp_id] = {"name": food_name, "mfp_id": mfp_id}

    # Fetch nutrition for each unique food
    foods_with_nutrition = []
    for mfp_id, food in list(all_foods.items())[:20]:  # cap at 20 to limit API calls
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
```

- [ ] **Step 4: Register in main.py**

Add import: `from bot.suggest import suggest_command`
Add handler: `application.add_handler(CommandHandler("suggest", suggest_command))`

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_suggest.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add bot/suggest.py main.py tests/test_suggest.py
git commit -m "feat: /suggest command recommends foods from history that fit remaining macros"
```

---

### Task 7: `/copy` command

**Files:**
- Modify: `bot/utility.py`
- Modify: `main.py`
- Modify: `bot/daily.py` (reuse `_get_target_date`, `_send_macro_update`)

- [ ] **Step 1: Implement copy_command in bot/utility.py**

Add to `bot/utility.py`:

```python
async def copy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.daily import _ensure_client, _get_target_date, _send_macro_update, DAY_NAMES
    from bot.messages import format_macro_summary
    from db.database import save_meal_entry, mark_entry_synced, get_meal_entries

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
        # _get_target_date returns future dates; we want past
        if source_date >= today:
            source_date -= timedelta(days=7)
    else:
        try:
            source_date = date.fromisoformat(arg)
        except ValueError:
            await update.message.reply_text("Usage: `/copy yesterday`, `/copy monday`, or `/copy 2026-04-12`",
                                            parse_mode="Markdown")
            return

    db = context.bot_data["db"]
    user_id = update.effective_user.id

    # Read source day entries
    source_entries = await get_meal_entries(db, user_id, source_date.isoformat())
    if not source_entries:
        await update.message.reply_text(f"No meals found for {source_date.isoformat()}.")
        return

    msg = await update.message.reply_text(f"Copying from {source_date.isoformat()}...")

    copied = 0
    skipped_slots = []
    slot_foods: dict[str, list[str]] = {}

    for entry in source_entries:
        # Check if today already has entries in this slot
        existing = await get_meal_entries(db, user_id, today.isoformat(), entry.slot)
        if existing:
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
            source="bot_confirm",
            synced_to_mfp=False,
        )
        entry_id = await save_meal_entry(db, new_entry)

        if client and entry.mfp_food_id and entry.mfp_food_id not in ("", "None"):
            try:
                await client.add_entry(today.isoformat(), entry.slot, entry.food_name, entry.mfp_food_id)
                await mark_entry_synced(db, entry_id)
            except Exception:
                pass

        slot_foods.setdefault(entry.slot, []).append(entry.food_name)
        copied += 1

    lines = [f"Copied {copied} entries from {source_date.isoformat()}:"]
    for slot, foods in slot_foods.items():
        lines.append(f"  {slot}: {', '.join(foods)}")
    if skipped_slots:
        lines.append(f"  Skipped (already filled): {', '.join(skipped_slots)}")

    await msg.edit_text("\n".join(lines))
    await _send_macro_update(update, context, today)
```

- [ ] **Step 2: Register in main.py**

Add `copy_command` to the import from `bot.utility`.
Add handler: `application.add_handler(CommandHandler("copy", copy_command))`

- [ ] **Step 3: Run all tests**

Run: `pytest -v --ignore=tests/test_integration_telegram.py`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add bot/utility.py main.py
git commit -m "feat: /copy command duplicates a day's meals to today"
```

---

### Task 8: `/history` command

**Files:**
- Modify: `bot/utility.py`
- Modify: `bot/messages.py`
- Modify: `main.py`
- Test: `tests/test_messages.py`

- [ ] **Step 1: Write test for format_history**

Add to `tests/test_messages.py`:

```python
def test_format_history():
    from bot.messages import format_history

    days = [
        {"date": "2026-04-07", "totals": {"calories": 2450, "protein": 175, "carbs": 290, "fat": 62}},
        {"date": "2026-04-08", "totals": {"calories": 2680, "protein": 190, "carbs": 310, "fat": 70}},
    ]
    goals = {"calories": 2505, "protein": 180, "carbs": 300, "fat": 65}

    result = format_history(days, goals)
    assert "Mon 07" in result or "Tue 08" in result
    assert "Average" in result
    assert "Target" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_messages.py::test_format_history -v`
Expected: FAIL — `cannot import name 'format_history'`

- [ ] **Step 3: Implement format_history in bot/messages.py**

Add to `bot/messages.py`:

```python
def format_history(days: list[dict], goals: dict) -> str:
    """Format a 7-day macro history with averages."""
    if not days:
        return "No data available."

    lines = ["Weekly history:"]
    sum_cal, sum_p, sum_c, sum_f = 0, 0, 0, 0

    for day in days:
        d = date.fromisoformat(day["date"])
        t = day["totals"]
        cal, p, c, f = t["calories"], t["protein"], t["carbs"], t["fat"]
        sum_cal += cal
        sum_p += p
        sum_c += c
        sum_f += f

        # Check if over 105% on any macro
        over = False
        if goals:
            over = (cal > goals["calories"] * 1.05 or p > goals["protein"] * 1.05
                    or c > goals["carbs"] * 1.05 or f > goals["fat"] * 1.05)
        on_target = False
        if goals and not over:
            on_target = (cal >= goals["calories"] * 0.95 and p >= goals["protein"] * 0.95)

        marker = " over" if over else (" ok" if on_target else "")
        lines.append(f"  {d.strftime('%a %d')}: {cal:.0f} cal | P:{p:.0f} C:{c:.0f} F:{f:.0f}{marker}")

    n = len(days)
    lines.append(f"\nAverage: {sum_cal/n:.0f} cal | P:{sum_p/n:.0f} C:{sum_c/n:.0f} F:{sum_f/n:.0f}")
    if goals:
        lines.append(f"Target:  {goals['calories']:.0f} cal | P:{goals['protein']:.0f} C:{goals['carbs']:.0f} F:{goals['fat']:.0f}")

    return "\n".join(lines)
```

- [ ] **Step 4: Implement history_command in bot/utility.py**

Add to `bot/utility.py`:

```python
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

    msg = await update.message.reply_text("Loading 7-day history...")

    today = date.today()
    days = []
    for i in range(6, -1, -1):  # 6 days ago → today
        d = today - timedelta(days=i)
        totals = await client.get_day_totals(d)
        days.append({"date": d.isoformat(), "totals": totals})

    text = format_history(days, goals or {})
    await msg.edit_text(text)
```

- [ ] **Step 5: Register in main.py**

Add `history_command` to the import from `bot.utility`.
Add handler: `application.add_handler(CommandHandler("history", history_command))`

- [ ] **Step 6: Run all tests**

Run: `pytest -v --ignore=tests/test_integration_telegram.py`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add bot/utility.py bot/messages.py main.py tests/test_messages.py
git commit -m "feat: /history command shows 7-day macro adherence"
```

---

### Task 9: Final integration — register all new commands with Telegram

**Files:**
- Modify: `tests/test_integration_telegram.py`

- [ ] **Step 1: Update test_set_bot_commands to include new commands**

In `tests/test_integration_telegram.py`, update the `test_set_bot_commands` test to include: `setup`, `macros`, `suggest`, `copy`, `history`.

```python
    commands = [
        BotCommand("start", "Connect to MFP"),
        BotCommand("token", "Set MFP auth token"),
        BotCommand("setup", "Register your typical foods"),
        BotCommand("today", "Plan today's meals"),
        BotCommand("tomorrow", "Plan tomorrow's meals"),
        BotCommand("day", "Plan a specific day"),
        BotCommand("week", "Plan the whole week"),
        BotCommand("macros", "Show remaining daily macros"),
        BotCommand("suggest", "Suggest foods that fit your macros"),
        BotCommand("copy", "Copy meals from another day"),
        BotCommand("history", "7-day macro history"),
        BotCommand("status", "Weekly status"),
        BotCommand("undo", "Remove last entry"),
        BotCommand("retry", "Retry failed syncs"),
    ]
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v --ignore=tests/test_integration_telegram.py`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_telegram.py
git commit -m "feat: register all new commands with Telegram"
```
