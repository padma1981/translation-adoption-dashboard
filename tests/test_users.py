"""User store rules (src/users.py) against the SQLite fallback."""

import pytest

from src import users
from tests.conftest import ADMIN, ADMIN_PASSWORD

GOOD = "Correct1horse"


def request(username="maria", role="supervisor", team="Echo", password=GOOD, confirm=None,
            email="maria@example.com", **kw):
    return users.create_request("Maria Lopez", email, username, password,
                                password if confirm is None else confirm, role, team,
                                "Coach my team", **kw)


def active(username="maria", role="supervisor", team="Echo"):
    assert request(username, role=role if role != "admin" else "viewer", team=team) == []
    users.approve(username, role, team, actor="admin")


def test_sqlite_fallback_is_used_without_sheets_secrets(user_store):
    assert users.backend() == "sqlite"
    request()
    assert user_store.exists()


def test_request_saved_as_pending_with_bcrypt_hash():
    assert request() == []
    user = users.get_user("MARIA")   # usernames are case-insensitive
    assert user["status"] == "pending" and user["requested_role"] == "supervisor"
    assert user["requested_team"] == "Echo" and user["role"] == ""
    assert "password_hash" not in user and "password_hash" not in users.list_users()
    stored = users._get("maria")["password_hash"]
    assert stored.startswith("$2") and GOOD not in stored


@pytest.mark.parametrize("kwargs, problem", [
    (dict(username="Maria"), "That username is already taken."),               # case-insensitive
    (dict(username="ADMIN", reserved=["admin"]), "That username is already taken."),
    (dict(username="new1", password="short1"), "at least 10 characters"),
    (dict(username="new2", password="lettersonlyhere"), "letters and numbers"),
    (dict(username="new3", password="1234567890123"), "letters and numbers"),
    (dict(username="new4", confirm="Different123"), "Passwords don't match."),
    (dict(username="new5", team=""), "Choose your team"),                      # supervisor needs team
    (dict(username="new6", role="admin"), "Requested role must be supervisor or viewer."),
    (dict(username="new7", email="not-an-email"), "Enter a valid email address."),
    (dict(username="x"), "Username must be 3-32 characters"),
])
def test_request_validation(kwargs, problem):
    assert request() == []
    problems = request(**kwargs)
    assert any(problem in p for p in problems), problems
    assert len(users.list_users()) == 1   # nothing saved


def test_viewer_request_needs_no_team():
    assert request(role="viewer", team="") == []
    assert users.get_user("maria")["requested_team"] == ""


def test_pending_user_cannot_sign_in():
    request()
    assert users.authenticate("maria", GOOD) == (None, "pending")
    assert users.authenticate("maria", "Wrong123456") == (None, "incorrect")   # status not revealed


def test_approve_then_sign_in_with_admin_choice_of_role():
    request()
    users.approve("maria", "viewer", "", actor="admin")   # admin overrides the requested role
    user, problem = users.authenticate("maria", GOOD)
    assert problem is None and user["role"] == "viewer" and user["team"] == ""
    record = users.get_user("maria")
    assert record["approved_by"] == "admin" and record["approved_at"]


def test_correct_and_incorrect_sign_in():
    active()
    user, problem = users.authenticate(" Maria ", GOOD)
    assert problem is None and user["username"] == "maria" and user["team"] == "Echo"
    assert users.authenticate("maria", "Correct1horsE") == (None, "incorrect")
    assert users.authenticate("nobody", GOOD) == (None, "incorrect")


def test_reject():
    request()
    users.reject("maria", actor="admin")
    assert users.get_user("maria")["status"] == "rejected"
    assert users.authenticate("maria", GOOD) == (None, "inactive")
    with pytest.raises(users.UserError):
        users.approve("maria", "viewer", "", actor="admin")


def test_deactivate_blocks_sign_in_and_reactivate_restores_it():
    active()
    users.deactivate("maria", actor="admin")
    assert users.authenticate("maria", GOOD) == (None, "inactive")
    users.reactivate("maria", actor="admin")
    assert users.authenticate("maria", GOOD)[1] is None


def test_admin_cannot_deactivate_or_demote_themselves():
    active("boss", role="admin", team="")
    with pytest.raises(users.UserError, match="deactivate your own"):
        users.deactivate("boss", actor="boss")
    with pytest.raises(users.UserError, match="own admin role"):
        users.set_role("boss", "viewer", "", actor="Boss")
    users.set_role("boss", "admin", "", actor="boss")   # keeping admin is fine
    assert users.get_user("boss")["status"] == "active"


def test_set_role_and_team():
    active()
    users.set_role("maria", "supervisor", "Atlas", actor="admin")
    assert users.get_user("maria")["team"] == "Atlas"
    users.set_role("maria", "viewer", "Atlas", actor="admin")
    assert users.get_user("maria")["team"] == ""   # team only kept for supervisors
    with pytest.raises(users.UserError):
        users.set_role("maria", "supervisor", "", actor="admin")


def test_change_password_requires_correct_current_password():
    active()
    assert users.change_password("maria", "Wrong123456", "Brandnew123", "Brandnew123") == \
        ["Current password is incorrect."]
    assert users.authenticate("maria", GOOD)[1] is None   # unchanged
    assert any("different" in p for p in users.change_password("maria", GOOD, GOOD, GOOD))
    assert any("at least 10" in p for p in users.change_password("maria", GOOD, "short1", "short1"))
    assert users.change_password("maria", GOOD, "Brandnew123", "Brandnew123") == []
    assert users.authenticate("maria", GOOD) == (None, "incorrect")
    assert users.authenticate("maria", "Brandnew123")[1] is None


def test_temporary_password_forces_a_change():
    active()
    temp = users.reset_password("maria", actor="admin")
    assert users.password_problems(temp, temp) == []
    assert users.authenticate("maria", GOOD) == (None, "incorrect")
    user, _ = users.authenticate("maria", temp)
    assert user["must_change_password"] is True
    assert users.change_password("maria", temp, "Brandnew123", "Brandnew123") == []
    user, _ = users.authenticate("maria", "Brandnew123")
    assert user["must_change_password"] is False


def test_break_glass_admin_works_when_store_unavailable(monkeypatch):
    def unavailable(*a, **k):
        raise ConnectionError("Google Sheets unreachable")
    monkeypatch.setattr(users, "_read", unavailable)
    user, problem = users.authenticate("Admin", ADMIN_PASSWORD, ADMIN)
    assert problem is None and user["role"] == "admin" and user["break_glass"]
    assert users.authenticate("admin", "Wrong123456", ADMIN) == (None, "incorrect")
    with pytest.raises(ConnectionError):   # other users need the store
        users.authenticate("maria", GOOD, ADMIN)
