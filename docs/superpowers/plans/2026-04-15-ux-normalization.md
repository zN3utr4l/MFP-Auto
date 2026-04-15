# UX Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align user-facing flows and messages around MyFitnessPal as the source of truth, with a clear `/undo` behavior and consistent slot/microcopy formatting.

**Architecture:** Keep the current bot structure, but centralize slot labels and source-of-truth decisions around existing MFP diary reads. Fix the highest-confusion flows first: `/undo`, `/week`, `/copy`, and shared message formatting.

**Tech Stack:** Python 3.14, python-telegram-bot, aiosqlite, pytest

---

### Task 1: Lock in message-formatting regressions

**Files:**
- Modify: `tests/test_messages.py`

- [ ] Add failing tests for high-confidence slot messages showing saved portion units from `unit` as well as legacy `serving_unit`.
- [ ] Run: `pytest tests/test_messages.py -q`
- [ ] Implement the minimal formatter change in `bot/messages.py`.
- [ ] Re-run: `pytest tests/test_messages.py -q`

### Task 2: Make `/undo` explicit and reliable

**Files:**
- Create: `tests/test_utility.py`
- Modify: `bot/utility.py`
- Modify: `mfp/client.py`
- Modify: `main.py`

- [ ] Add a failing test for `/undo` deleting the latest MFP entry for today and removing only the best-matching local row.
- [ ] Add a failing test for `/undo` response text explicitly describing that it removed the most recent MFP entry for today.
- [ ] Run: `pytest tests/test_utility.py -k undo -q`
- [ ] Implement the minimal matching and microcopy updates.
- [ ] Re-run: `pytest tests/test_utility.py -k undo -q`

### Task 3: Make `/week` and `/copy` honor MFP as source of truth

**Files:**
- Create: `tests/test_week.py`
- Modify: `tests/test_utility.py`
- Modify: `bot/week.py`
- Modify: `bot/utility.py`

- [ ] Add a failing test for week flow skipping days already filled in MFP even if local DB is empty.
- [ ] Add a failing test for `/copy` skipping slots already filled in MFP even if local DB is empty.
- [ ] Run: `pytest tests/test_week.py tests/test_utility.py -k "week or copy" -q`
- [ ] Implement the minimal source-of-truth changes using existing MFP diary helpers.
- [ ] Re-run: `pytest tests/test_week.py tests/test_utility.py -k "week or copy" -q`

### Task 4: Normalize user-facing slot and state microcopy

**Files:**
- Modify: `tests/test_daily.py`
- Modify: `bot/daily.py`
- Modify: `bot/setup.py`
- Modify: `bot/utility.py`

- [ ] Add failing tests for slot-facing strings using labels instead of internal keys like `snacks`.
- [ ] Add failing tests for sync-failure and stale-button messages to explain the next action clearly.
- [ ] Run: `pytest tests/test_daily.py -q`
- [ ] Implement the minimal message normalization.
- [ ] Re-run: `pytest tests/test_daily.py -q`

### Task 5: Full verification

**Files:**
- Verify only

- [ ] Run: `pytest tests/test_messages.py tests/test_daily.py tests/test_week.py tests/test_utility.py tests/test_mfp_client.py tests/test_sync.py -q`
- [ ] Run: `pytest -q`
- [ ] Inspect `git diff --stat` and confirm only intended files changed.
