from __future__ import annotations

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import DB_PATH, TELEGRAM_BOT_TOKEN
from db.database import get_db


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass  # suppress logs


def _start_health_server() -> None:
    """Start a minimal HTTP server for Render health checks."""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Health check server on port {port}")


async def post_init(application: Application) -> None:
    """Called after Application.initialize(). Set up DB connection."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    application.bot_data["db"] = await get_db(DB_PATH)


async def post_shutdown(application: Application) -> None:
    """Called during Application.shutdown(). Close DB."""
    db = application.bot_data.get("db")
    if db:
        await db.close()


def main() -> None:
    from bot.daily import day_command, search_text_handler, slot_callback, today_command, tomorrow_command
    from bot.onboarding import import_callback, login_command, start_command
    from bot.utility import retry_command, status_command, undo_command
    from bot.week import week_command, week_stop_callback

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("day", day_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("retry", retry_command))

    # Callback handlers — order matters (more specific patterns first)
    application.add_handler(CallbackQueryHandler(import_callback, pattern=r"^import:"))
    application.add_handler(CallbackQueryHandler(week_stop_callback, pattern=r"^week:stop$"))
    application.add_handler(CallbackQueryHandler(slot_callback, pattern=r"^(confirm|change|skip|pick|search|search_pick|back):"))

    # Free-text search handler (only when user is in search mode)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_text_handler))

    _start_health_server()
    print("Bot starting... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
