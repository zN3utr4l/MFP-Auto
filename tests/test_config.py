import os

import pytest


def test_config_reads_env_vars(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("ENCRYPTION_KEY", "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=")

    # Force reimport to pick up new env
    import importlib
    import config
    importlib.reload(config)

    assert config.TELEGRAM_BOT_TOKEN == "test-token-123"
    assert config.ENCRYPTION_KEY == "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI="


def test_config_raises_on_missing_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ENCRYPTION_KEY", "some-key")

    import importlib
    import config

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        importlib.reload(config)
