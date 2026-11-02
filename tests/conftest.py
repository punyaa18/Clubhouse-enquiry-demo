import importlib

import pytest

import db


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    """Reload app.py against a fresh temp database for each test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
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
