import os

from dotenv import load_dotenv

# Load .env first so real credentials are available for integration tests
load_dotenv()

# Fallback for unit tests (only if .env doesn't provide them)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-for-pytest")
os.environ.setdefault("ENCRYPTION_KEY", "ljblj2nO_zoxnnQaY8fgN35KyYJlIaj6RIds7ea15oc=")
