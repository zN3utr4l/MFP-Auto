# New Features Design — 2026-04-13

## Context

MFP Auto Bot used by 2 users (brothers, separate MFP accounts) for gym diet tracking. Core flow (predict → confirm → log → macro check) is working. These features address remaining friction points.

## 1. Serving Size & Quantity in Patterns

### Problem
Bot logs food with default serving_size (index 0) and servings=1. Users need specific portions (e.g., 80g oats, not "1 serving").

### Design
- MFP search API returns `serving_sizes` per food: `[{value, unit, nutrition_multiplier, id, index}, ...]`
- After picking a food (in `/setup` or search), show serving_sizes as inline buttons (max 6)
- After picking serving_size, show servings quantity buttons: `[0.5] [1] [1.5] [2] [type amount]`
- For free-text amount: user types a number, bot parses it
- Pattern stores new fields: `serving_size_index` (int), `servings` (float), `serving_unit` (str)
- `add_entry_sync` uses the pattern's serving data instead of defaults
- On confirm (high-confidence): uses saved serving_size + servings from pattern — one tap

### Data changes
- `meal_patterns` table: add `serving_info TEXT DEFAULT '{}'` — JSON with `{serving_size_index, servings, serving_unit, nutrition_multiplier}`
- `MealPattern` dataclass: add `serving_info: str = '{}'`
- Backwards compatible: empty JSON = use defaults (existing patterns still work)

### Flow
```
/setup → search "avena" → pick "Instant oats" 
  → [100g] [1 cup] [1 packet] [serving]     ← serving_size buttons
  → picked "100g"
  → [0.5] [1] [1.5] [2] [custom]            ← servings buttons  
  → picked "0.8"
  → "Instant oats (80g) saved for Breakfast"
  
/today → Breakfast: "Instant oats (80g)" [Confirm] [Change] [Skip]
  → Confirm → logged with serving_size=100g, servings=0.8
```

## 2. Evening Reminder

### Problem
Users forget to log meals.

### Design
- Use `python-telegram-bot`'s `JobQueue` for scheduling
- On bot startup (`post_init`): schedule a daily job at 21:00 UTC+2 (Italy)
- Job queries all users, for each: count today's empty slots
- If empty slots > 0: send message "You have N slots not logged today. Use /today to fill them"
- Runs every day including weekends
- Time hardcoded to 21:00 for now (REMINDER_HOUR in config.py)

### Implementation
- New file: `bot/reminder.py` with `schedule_reminders(application)` and `_check_daily(context)`
- Called from `post_init` in `main.py`
- Uses `context.job_queue.run_daily(callback, time=time(21, 0))`

## 3. `/macros` Command

### Problem
User wants to check remaining macros without logging a meal.

### Design
- Reads goals from `v2/nutrient-goals` (cached in user_data)
- Reads today's totals from `v2/diary`
- Shows same `format_macro_summary()` output
- Added to `bot/utility.py`

### Output
```
Daily macros:
  Cal: 1450/2505
  Protein: 95/180g (85 left)
  Carbs: 180/300g
  Fat: 42/65g
```

## 4. `/suggest` Command

### Problem
User has macro budget left and wants to know what to eat from their usual foods.

### Design
- Calculate remaining macros: goals - today's totals
- Load user's patterns from DB (all slots, both day_types)
- For each pattern's food, get nutritional info via search API (cache results in user_data for session)
- Filter: food fits within remaining macros (doesn't push any macro over goal)
- Sort by protein content (gym diet = protein priority)
- Show top 5 with their macros

### Output
```
You have left: 500 cal, 85g protein, 120g carbs, 23g fat

Suggested from your foods:
1. Greek yogurt (130 cal, 12g P, 5g C, 4g F)
2. Chicken breast 150g (248 cal, 46g P, 0g C, 5g F)
3. Tuna can (116 cal, 26g P, 0g C, 1g F)
```

### Note
- Only suggests foods the user has previously logged (from patterns) — not random search results
- If no patterns fit remaining macros, say "No foods from your history fit. Try /today to search manually"
- Nutritional info comes from MFP search API response (`nutritional_contents` field)

## 5. `/copy` Command

### Problem
Many days are identical (especially weekday meal prep). User wants to copy a whole day.

### Design
- Syntax: `/copy yesterday`, `/copy monday`, `/copy 2026-04-12`
- Reads source day's entries from `meals_history` DB
- For each entry: creates new MealEntry for today, syncs to MFP
- Boosts patterns via `on_confirm` for each entry
- Shows summary with macro totals

### Output
```
Copied 5 entries from yesterday to today:
  Breakfast: Oatmeal 80g, Banana
  Lunch: Chicken breast 150g, Rice 200g
  Dinner: (empty — nothing to copy)

Daily macros:
  Cal: 1850/2505
  ...
```

### Edge cases
- Source day has no entries → "No meals found for yesterday"
- Today already has entries in a slot → skip that slot, mention it
- Entry has no mfp_food_id → copy locally but don't sync to MFP

## 6. `/history` Command

### Problem
User wants to see weekly macro adherence and trends.

### Design
- Shows last 7 days (today back to 7 days ago)
- For each day: reads diary totals from MFP API
- Compares to goals
- Shows daily summary + weekly average

### Output
```
Weekly history:
  Mon 07: 2450 cal | P:175 C:290 F:62 ✓
  Tue 08: 2680 cal | P:190 C:310 F:70 ⚠ over
  Wed 09: 2100 cal | P:155 C:240 F:55
  Thu 10: 2500 cal | P:180 C:300 F:65 ✓
  Fri 11: 2350 cal | P:170 C:280 F:60
  Sat 12: 1900 cal | P:140 C:220 F:50
  Sun 13: 2228 cal | P:168 C:250 F:58

Average: 2315 cal | P:168 C:270 F:60
Target: 2505 cal | P:180 C:300 F:65
```

### Note
- 7 API calls (one per day) — rate limited, may take a few seconds
- Send a "Loading..." message first, then edit with results
- `✓` when all macros within 5% of goal, `⚠` when any macro >105% of goal
