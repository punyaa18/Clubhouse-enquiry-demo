import importlib
import smtplib

import dotenv
import pytest

import db
import mailer

CSRF = "test-csrf-token"
ENV_VARS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "REPLY_TO",
            "EMAILS_ENABLED", "MAX_EMAILS_PER_DAY", "SECRET_KEY"]


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    """Reload app.py against a fresh, empty temp database for each test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    # never pick up a developer's real .env: tests must not send real email
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AUTO_SEED", "0")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod


@pytest.fixture
def client(app_module):
    test_client = app_module.app.test_client()
    with test_client.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return test_client


@pytest.fixture
def conn(app_module):
    connection = db.get_connection(db.DB_PATH)
    yield connection
    connection.close()


class FakeSender:
    """Stands in for mailer.send: records messages, or raises `error` if set."""

    def __init__(self):
        self.sent = []
        self.error = None

    def __call__(self, to_address, subject, body):
        if self.error:
            raise self.error
        self.sent.append({"to": to_address, "subject": subject, "body": body})


@pytest.fixture
def fake_sender(app_module, monkeypatch):
    """Real-sending mode with a fake SMTP sender."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "club@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    sender = FakeSender()
    monkeypatch.setattr(mailer, "send", sender)
    return sender


@pytest.fixture
def auth_error():
    return smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
