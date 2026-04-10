# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MFP Auto Bot — a Telegram bot that automates meal logging on MyFitnessPal by analyzing the user's eating history to predict recurring meals. Multi-user, supports both MFP Premium and free accounts. Written in Italian-facing UX, English codebase.

Design spec: `docs/specs/design.md`
Implementation plan: `docs/plans/2026-04-10-mfp-auto-implementation.md`

## Tech Stack

- Python 3.14, async throughout
- python-telegram-bot 22.7 (async long-polling)
- myfitnesspal 2.1.2 (sync library — all calls via `asyncio.to_thread()`)
- pandas >=2.2 for pattern analysis
- aiosqlite >=0.21 for async SQLite
- cryptography >=44.0 (Fernet encryption for stored MFP credentials)

## Virtual Environment

The project uses a local venv (`.venv/`). Always activate it before running anything:

```bash
# Windows (Git Bash)
source .venv/Scripts/activate

# Create venv (first time only)
python -m venv .venv
```

## Commands

All commands assume the venv is active.

```bash
# Install dependencies
pip install -r requirements.txt

# Run bot
python main.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_predictor.py

# Run a specific test
pytest tests/test_predictor.py::test_predict_day_weekday -v
```

## Architecture

Three layers, all async, orchestrated from `main.py`:

1. **Bot Engine** (`bot/`) — Telegram handlers, inline keyboards, message formatting. Split by flow:
   - `onboarding.py` — /start, /login, import range selection, snack mapping wizard
   - `daily.py` — /today, /tomorrow, /day (single-day slot-by-slot flow)
   - `week.py` — /week (multi-day sequential wizard with stop/resume)
   - `utility.py` — /status, /undo, /retry

2. **Pattern Engine** (`engine/`) — Predicts meals from history:
   - `pattern_analyzer.py` — computes meal_patterns from meals_history with temporal decay (weight = base * 0.95^weeks)
   - `predictor.py` — generates predictions per day/slot (>70% confidence = auto-suggest, <70% = show top 3)
   - `learner.py` — updates pattern weights on confirm/replace/skip

3. **MFP Client** (`mfp/`) — Wraps python-myfitnesspal:
   - `client.py` — get_day(), search_food(), add_entry()
   - `scraper.py` — iterates date range, populates meals_history (rate-limited: 1 req/sec)
   - `sync.py` — retry queue for failed MFP writes

**Data layer** (`db/`) — aiosqlite with 4 tables: `users`, `meals_history`, `meal_patterns`, `week_progress`. Models as dataclasses in `models.py`.

## Key Design Decisions

- MFP credentials are Fernet-encrypted in SQLite; the `/login` message is deleted immediately from Telegram chat
- 7 meal slots (breakfast, morning_snack, lunch, afternoon_snack, pre_workout, post_workout, dinner) — maps to MFP's custom meal names
- Pattern decay uses a ~3-month sliding window: `weight * 0.95^(weeks_elapsed)`
- Confirmed meals are saved locally even if MFP write fails; `/retry` syncs the backlog
- The `/week` wizard is resumable — tracks progress in `week_progress` table, auto-saves on 30min inactivity timeout

## Environment Variables

- `TELEGRAM_BOT_TOKEN` — from BotFather
- `ENCRYPTION_KEY` — Fernet key for encrypting MFP credentials in the DB

## Deployment

PythonAnywhere free tier — single always-on task running `python main.py`.
