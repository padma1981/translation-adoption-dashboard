"""Shared test setup: every test gets its own SQLite user store, and app tests run
with a test break-glass admin in secrets."""

from pathlib import Path
import time

import bcrypt
import pytest
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
ADMIN_PASSWORD = "BreakGlass123"
ADMIN = {"username": "admin", "name": "Test Admin",
         # 4 rounds keeps tests fast; checkpw reads the cost from the hash
         "password_hash": bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt(4)).decode()}
AUTH = {"session_timeout_minutes": 480, "admin": ADMIN}
ADMIN_SESSION = {"username": "admin", "name": "Test Admin", "role": "admin", "team": "",
                 "must_change_password": False, "break_glass": True}


@pytest.fixture(autouse=True)
def user_store(tmp_path, monkeypatch):
    """A fresh SQLite user store per test (the fallback used without Sheets secrets)."""
    path = tmp_path / "users.db"
    monkeypatch.setenv("USERS_DB_PATH", str(path))
    return path


def new_app(auth=AUTH) -> AppTest:
    at = AppTest.from_file(ENTRY, default_timeout=120)
    if auth is not None:
        at.secrets["auth"] = auth
    return at


def signed_in(at: AppTest, user=ADMIN_SESSION) -> AppTest:
    """Put a signed-in user into the session (as the sign-in form would)."""
    now = time.time()
    at.session_state["user"] = dict(user)
    at.session_state["signed_in_at"] = now
    at.session_state["_user_checked_at"] = now
    return at
