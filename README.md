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

## Deploy to PythonAnywhere (Free)

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Upload project files (or clone from git)
3. Open a Bash console and install: `pip install -r requirements.txt`
4. Set environment variables in the "Tasks" tab
5. Create an "Always-on task": `python /home/yourusername/mfp-auto/main.py`
6. Renew free tier every 3 months (email reminder sent)

## Tech Stack

- Python 3.14
- python-telegram-bot 22.7
- python-myfitnesspal 2.1.2
- SQLite (via aiosqlite)
- pandas
