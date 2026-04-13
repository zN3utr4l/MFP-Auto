# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MFP Auto Bot — a Telegram bot that automates meal logging on MyFitnessPal by learning eating patterns and predicting recurring meals. Multi-user, tracks macros in real time. English codebase.

## Tech Stack

- Python 3.14, async throughout
- python-telegram-bot 22.7 (async long-polling)
- curl_cffi >=0.15 (Chrome TLS impersonation for MFP API)
- pandas >=2.2 for pattern analysis
- aiosqlite >=0.21 for async SQLite
- cryptography >=44.0 (Fernet encryption for stored MFP tokens)
- lxml >=5.0

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

# Run unit tests
pytest --ignore=tests/test_integration_telegram.py --ignore=tests/test_integration_mfp.py

# Run integration tests (need real tokens in .env)
pytest tests/test_integration_mfp.py -v -s

# Run all tests
pytest -v
```

## Architecture

Three layers, all async, orchestrated from `main.py`:

1. **Bot Engine** (`bot/`) — Telegram handlers, inline keyboards, message formatting:
   - `onboarding.py` — /start (step-by-step wizard), /token (auth with immediate message deletion)
   - `setup.py` — /setup (register foods per slot with serving_size + quantity selection)
   - `daily.py` — /today, /tomorrow, /day (slot-by-slot with macro tracking after each confirm)
   - `week.py` — /week (7-day wizard with 30min timeout auto-stop, stop/resume)
   - `suggest.py` — /suggest (macro-aware food suggestions from user's pattern history)
   - `utility.py` — /status, /undo, /retry, /macros, /copy, /history
   - `reminder.py` — daily 21:00 reminder for unfilled slots (JobQueue)
   - `keyboards.py` — inline button builders (slots, alternatives, serving sizes, quantities)
   - `messages.py` — formatting (slots, macros summary, history)

2. **Pattern Engine** (`engine/`) — Predicts meals from history:
   - `pattern_analyzer.py` — computes meal_patterns with temporal decay (weight = base * 0.95^weeks)
   - `predictor.py` — predictions per day/slot with serving_info (>70% = auto-suggest, <70% = top 3)
   - `learner.py` — updates pattern weights on confirm/replace

3. **MFP Client** (`mfp/`) — MFP JSON API via curl_cffi:
   - `client.py` — validate, get_day, search_food (with serving_sizes + nutrition), add_entry (with servings params), get_nutrient_goals, get_day_totals
   - `scraper.py` — date range import (rate-limited 1 req/sec)
   - `sync.py` — retry queue for failed MFP writes

**Data layer** (`db/`) — aiosqlite with 4 tables: `users`, `meals_history`, `meal_patterns` (with serving_info), `week_progress`. Models as dataclasses in `models.py`.

## Key Design Decisions

- MFP auth tokens are Fernet-encrypted in SQLite; `/token` message is deleted immediately
- 7 meal slots (breakfast, morning_snack, lunch, afternoon_snack, pre_workout, post_workout, dinner) mapped to MFP meal_positions (0-3)
- Pattern decay: `weight * 0.95^(weeks_elapsed)`
- Patterns store serving_info (serving_size_index, servings, unit, nutrition_multiplier)
- Macro tracking after each confirm — reads goals from `v2/nutrient-goals`, totals from `v2/diary`
- Token expiration detected in `_ensure_client` — suggests `/token` refresh
- `/week` wizard auto-stops after 30min inactivity
- Evening reminder at 21:00 for unfilled slots

## Environment Variables

- `TELEGRAM_BOT_TOKEN` — from BotFather
- `ENCRYPTION_KEY` — Fernet key for encrypting MFP tokens in DB

## Deployment

Render — `render.yaml` configured, health check on port 10000.
