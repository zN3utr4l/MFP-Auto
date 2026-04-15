# MFP Auto Bot

Telegram bot that auto-logs meals on MyFitnessPal by learning your eating patterns. Predicts recurring meals, tracks macros in real time, and suggests foods that fit your remaining budget.

Built for gym diet tracking — optimizes for hitting protein/carbs/fat targets.

## How It Works

1. Connect your MFP account via `/start`
2. Run `/setup` to register your typical foods (with exact portions)
3. Use `/today` — the bot predicts your meals, you confirm with one tap
4. After each confirmation, see your macro progress vs goals
5. The bot learns: the more you use it, the better the predictions

## Bot Commands

| Command | What it does |
|---------|-------------|
| `/start` | Step-by-step guide to connect your MFP account |
| `/token <json>` | Authenticate with MFP (token is deleted from chat immediately) |
| `/setup` | Register your typical foods per meal slot with portions |
| `/today` | Log today's meals — slot by slot with predictions |
| `/tomorrow` | Same, for tomorrow |
| `/day Mon` | Log meals for a specific day |
| `/week` | 7-day wizard with stop/resume |
| `/macros` | Check remaining macros for today |
| `/suggest` | Foods from your history that fit remaining macros |
| `/copy yesterday` | Copy all meals from another day to today |
| `/history` | 7-day macro adherence overview |
| `/status` | Slots filled/pending per day |
| `/undo` | Remove the latest food entry from MFP for today |
| `/retry` | Retry failed MFP syncs |

## Getting Started (User)

After starting the bot on Telegram:

1. Send `/start` — the bot explains how to get your MFP token
2. Log into [myfitnesspal.com](https://www.myfitnesspal.com) in your browser
3. Visit `https://www.myfitnesspal.com/user/auth_token?refresh=true`
4. Copy ALL the JSON text on that page
5. Send `/token <paste here>` to the bot
6. Run `/setup` to configure your typical foods with exact portions
7. Done! Use `/today` to start logging

The token expires after some time. When it does, the bot tells you to refresh it with `/token`.

## Dev Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather)
2. Generate a Fernet key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Copy `.env.example` to `.env` and fill in the values
4. Create venv and install:
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate  # Windows Git Bash
   pip install -r requirements.txt
   ```
5. Run:
   ```bash
   python main.py
   ```

## Testing

```bash
# Unit tests (always work, no credentials needed)
pytest --ignore=tests/test_integration_telegram.py --ignore=tests/test_integration_mfp.py

# Integration tests (need real tokens in .env)
pytest tests/test_integration_mfp.py -v -s
pytest tests/test_integration_telegram.py -v -s

# All tests
pytest -v
```

Integration tests require `TELEGRAM_TEST_CHAT_ID` and `MFP_AUTH_JSON` in `.env` (see `.env.example`).

## Deployment

Deployed on **Render** with auto-deploy from GitHub.

1. Fork this repo
2. Create a Web Service on [render.com](https://render.com)
3. Set environment variables: `TELEGRAM_BOT_TOKEN`, `ENCRYPTION_KEY`
4. Deploy — `render.yaml` handles the rest

## Architecture

```
main.py              Entry point, health check, handler registration
config.py            Env vars, meal slots, thresholds

bot/
  onboarding.py      /start, /token — step-by-step connection wizard
  setup.py           /setup — register foods with serving sizes per slot
  daily.py           /today, /tomorrow, /day — slot-by-slot with macro tracking
  week.py            /week — 7-day wizard with timeout and stop/resume
  suggest.py         /suggest — macro-aware food suggestions from history
  utility.py         /status, /undo, /retry, /macros, /copy, /history
  reminder.py        Daily 21:00 reminder for unfilled slots
  keyboards.py       Inline button builders (confirm, alternatives, serving sizes)
  messages.py        Message formatting (slots, macros, history)

engine/
  pattern_analyzer.py  Meal pattern extraction with temporal decay
  predictor.py         Daily predictions per slot with confidence levels
  learner.py           Weight updates on confirm/replace feedback

mfp/
  client.py           MFP API client (auth, diary, search, add entry, goals)
  scraper.py           History import (rate-limited)
  sync.py              Retry queue for failed writes

db/
  database.py          Async SQLite CRUD + Fernet encryption
  models.py            User, MealEntry, MealPattern, WeekProgress
```

## Tech Stack

- Python 3.14, async throughout
- python-telegram-bot 22.7
- curl_cffi (Chrome TLS impersonation for MFP API)
- aiosqlite + SQLite
- pandas (pattern analysis)
- cryptography (Fernet encryption for stored tokens)
