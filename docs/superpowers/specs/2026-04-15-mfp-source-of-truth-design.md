# MFP as Source of Truth — Design Spec

**Date:** 2026-04-15
**Status:** Approved
**Approach:** C — MFP for live reads, DB local for patterns + retry queue

## Problem

The bot maintains a local `meals_history` table that duplicates MFP diary data. This causes:

1. `/undo` deletes from local DB but not MFP — diary goes out of sync
2. `/today` checks both MFP and local DB — confused about which slots are filled
3. Edits made in MFP app are invisible to the bot
4. No way to delete entries from MFP via the bot

## Verified API Capabilities

- `GET v2/diary/read_diary?entry_date=YYYY-MM-DD&types=food_entry` — reads entries with UUIDs
- `POST v2/diary` — adds entries
- `DELETE v2/diary/{entry_uuid}` — deletes entry, returns 204
- `GET v2/foods/{food_id}` — direct food lookup by ID (version + serving_sizes)

## Data Store Roles

| Store | Contains | Used for |
|-------|----------|----------|
| **MFP API** (source of truth) | Current diary | Filled slots, macros, undo, all live reads |
| **`meals_history`** (import archive) | History imported from MFP | Pattern engine (`/analyze`), written only by `/import` and confirm/pick |
| **`meal_patterns`** | Computed patterns | Predictions for `/today`, `/tomorrow` |
| **Retry queue** (`synced_to_mfp=0` rows) | Failed sync entries | `/retry` to re-sync |

**Key rule:** No live decision (is a slot filled? what to undo? current macros?) reads from `meals_history`. That table is only an archive for building patterns.

## Command Changes

### Modified Commands

**`/today`, `/tomorrow`, `/day`**
- Before: checks `mfp_filled` + `get_meal_entries` from local DB
- After: checks **only MFP** via `_fetch_mfp_filled_slots`. Local DB not consulted for filled slots.

**`/undo`**
- Before: deletes last entry from local DB, tells user to remove manually from MFP
- After:
  1. Calls `read_diary` for today
  2. Takes the most recent entry (by `created_at` DESC)
  3. Calls `DELETE v2/diary/{uuid}`
  4. If entry also exists in local DB, removes it
  5. Confirms to user what was deleted

**`/import`**
- Before: deletes ALL `mfp_scrape` entries then re-imports
- After: deletes only `mfp_scrape` entries **within the imported date range**, then re-imports that range

**`/status`**
- Before: mix of local DB + MFP
- After: only MFP for counting filled slots

**`/retry`**
- Unchanged — re-syncs entries with `synced_to_mfp=0`

### New Commands

**`/pending`**
- Lists unsynced entries (`synced_to_mfp=0`) with: date, slot, food name, last error
- If empty: "All synced!"
- Suggests `/retry` to retry or `/reset` to clean up

**`/reset`**
- Factory reset: deletes all `meals_history`, `meal_patterns`, and `week_progress` for the user
- Requires confirmation: `/reset confirm`
- Does NOT touch MFP data or user account

## Confirm/Pick Flow Change

When user confirms a food:
1. Write to MFP via `add_entry` (priority)
2. If MFP OK: save to `meals_history` with `synced_to_mfp=1`
3. If MFP fails: save to `meals_history` with `synced_to_mfp=0` (retry queue)

This keeps `meals_history` useful for patterns but never makes it the source of truth for "what's in the diary today."

## MFP Client Changes

New methods:

```
MfpClient:
  delete_entry_sync(entry_uuid: str) -> bool
    DELETE v2/diary/{entry_uuid} -> 204

  delete_entry(entry_uuid: str) -> bool   # async wrapper

  get_recent_entries_sync(target_date: date) -> list[dict]
    Calls read_diary, returns entries sorted by created_at DESC
    Each entry: uuid, food_name, slot, created_at, mfp_food_id
```

Existing methods (`add_entry`, `get_day`, `search_food`) unchanged.

## Error Handling

- **MFP down during `/today`**: show "Could not reach MFP, try again later" — no fallback to local DB
- **MFP down during confirm**: save to retry queue, show warning with `/retry`
- **`/undo` on empty day**: "Nothing to undo for today"
- **`/undo` on entry added via MFP app**: works — deletes the last MFP entry regardless of source
- **`/reset` without confirmation**: asks "Are you sure? Type `/reset confirm`"
- **`/pending` with old errors**: shows entry date, suggests `/reset` or manual logging if older than 7 days

## Files to Modify

- `mfp/client.py` — add `delete_entry`, `get_recent_entries`, verified `v2/foods/{id}` lookup
- `bot/utility.py` — rewrite `/undo`, add `/pending`, add `/reset`
- `bot/daily.py` — remove `get_meal_entries` check from `_send_next_slot`, rely only on `mfp_filled`
- `mfp/scraper.py` — scoped delete (only imported date range)
- `main.py` — register new command handlers
- `tests/` — integration test for DELETE, unit tests for new commands
