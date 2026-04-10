# MFP Auto Bot

Telegram bot that auto-logs meals on MyFitnessPal based on your eating patterns.

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and get the token
2. Generate a Fernet encryption key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Copy `.env.example` to `.env` and fill in the values
4. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate  # Windows Git Bash
   # or: source .venv/bin/activate  # Linux/Mac
   ```
5. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
6. Run:
   ```bash
   python main.py
   ```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Set up your account |
| `/login user pass` | Connect your MFP account |
| `/today` | Log today's meals |
| `/tomorrow` | Log tomorrow's meals |
| `/week` | Log meals for the next 7 days |
| `/day Mon` | Log meals for a specific day |
| `/status` | See weekly overview |
| `/undo` | Remove last logged entry |
| `/retry` | Retry failed MFP syncs |

## Deployment

The bot is deployed on **Render** (free tier) with auto-deploy from GitHub.

**Live URL:** https://mfp-auto.onrender.com

### Deploy your own instance

1. Fork this repo on GitHub
2. Sign up at [render.com](https://render.com) with your GitHub account
3. Create a new **Web Service** and connect the repo
4. Render auto-detects `render.yaml`. Set the environment variables:
   - `TELEGRAM_BOT_TOKEN` — from BotFather
   - `ENCRYPTION_KEY` — Fernet key (see Setup step 2)
5. Click **Create Web Service** — deploys automatically on every push

## Tech Stack

- Python 3.14
- python-telegram-bot 22.7
- cloudscraper + lxml (direct MFP web scraping)
- SQLite (via aiosqlite)
- pandas
