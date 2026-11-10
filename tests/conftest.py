import importlib

import dotenv
import pytest

import db

SMTP_VARS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    """Reload app.py against a fresh temp database for each test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    # never pick up a developer's real .env: tests must not send real email
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for var in SMTP_VARS:
        monkeypatch.delenv(var, raising=False)
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture
def conn(app_module):
    connection = db.get_connection(db.DB_PATH)
    yield connection
    connection.close()
