"""Dashboard users: sign-up requests, approval, roles and passwords.

All user records go through this module. They live in the "users" worksheet of
the Google Sheet (st-gsheets-connection, credentials from st.secrets) and fall
back to a local SQLite file (data/users/users.db, or $USERS_DB_PATH) when no
Sheets connection is configured. The break-glass admin lives in st.secrets
[auth.admin], not in the store, so it works even when the store is unavailable.

Passwords are stored only as bcrypt hashes. Nothing here logs or returns them.
"""

from datetime import datetime, timezone
from pathlib import Path
import os
import re
import secrets
import sqlite3

import bcrypt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "users" / "users.db"
WORKSHEET = "users"

COLUMNS = ["username", "name", "email", "role", "team", "password_hash", "status",
           "must_change_password", "requested_role", "requested_team", "reason",
           "created_at", "approved_by", "approved_at", "updated_at"]
PUBLIC_COLUMNS = [c for c in COLUMNS if c != "password_hash"]
ROLES = ("admin", "supervisor", "viewer")
REQUESTABLE_ROLES = ("supervisor", "viewer")
MIN_PASSWORD_LEN = 10
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class UserError(ValueError):
    """A request the store refuses (unknown user, self-demotion, bad role...)."""


# --- Passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str) -> bool:
    """bcrypt.checkpw that treats a missing or malformed hash as a mismatch."""
    try:
        return bcrypt.checkpw((password or "").encode(), (password_hash or "").encode())
    except ValueError:
        return False


def password_problems(password: str, confirm: str) -> list[str]:
    """Rule violations for a new password (empty list = OK)."""
    problems = []
    if len(password or "") < MIN_PASSWORD_LEN or not re.search(r"[A-Za-z]", password or "") \
            or not re.search(r"\d", password or ""):
        problems.append(f"Password must be at least {MIN_PASSWORD_LEN} characters and include "
                        "letters and numbers.")
    if password != confirm:
        problems.append("Passwords don't match.")
    return problems


def temporary_password() -> str:
    """Random password that meets the rules (letters and digits guaranteed)."""
    while True:
        pw = secrets.token_urlsafe(9)   # 12 characters
        if re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw):
            return pw


# --- Storage backends ----------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _sheets_configured() -> bool:
    try:
        import streamlit as st
        return "connections" in st.secrets and "gsheets" in st.secrets["connections"]
    except Exception:   # no secrets file, or not running under Streamlit
        return False


def backend() -> str:
    """'sheets' when a Google Sheets connection is configured, else 'sqlite'."""
    return "sheets" if _sheets_configured() else "sqlite"


def _db_path() -> Path:
    return Path(os.environ.get("USERS_DB_PATH") or DEFAULT_DB)


def _sqlite():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cols = ", ".join(f"{c} text" + (" primary key" if c == "username" else "") for c in COLUMNS)
    con.execute(f"create table if not exists users ({cols})")
    return con


def _sheet():
    import streamlit as st
    from streamlit_gsheets import GSheetsConnection
    return st.connection("gsheets", type=GSheetsConnection)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """All columns present, as strings, blanks for missing values."""
    df = df.reindex(columns=COLUMNS)
    df = df.dropna(how="all").fillna("").astype(str)
    df["must_change_password"] = df["must_change_password"].str.upper().isin(["TRUE", "1"])
    df["username"] = df["username"].str.strip().str.lower()
    return df[df["username"] != ""].reset_index(drop=True)


def _read() -> pd.DataFrame:
    if backend() == "sheets":
        return _clean(_sheet().read(worksheet=WORKSHEET, ttl=0))
    with _sqlite() as con:
        return _clean(pd.read_sql_query("select * from users", con))


def _write(record: dict):
    """Insert or replace one user record."""
    record = {c: record.get(c, "") for c in COLUMNS}
    flag = str(record["must_change_password"]).upper() in ("TRUE", "1")
    record["must_change_password"] = "TRUE" if flag else "FALSE"
    record = {c: "" if v is None else str(v) for c, v in record.items()}
    if backend() == "sheets":
        df = _read()
        df["must_change_password"] = df["must_change_password"].map({True: "TRUE", False: "FALSE"})
        df = pd.concat([df[df["username"] != record["username"]], pd.DataFrame([record])])
        _sheet().update(worksheet=WORKSHEET, data=df[COLUMNS])
        return
    with _sqlite() as con:
        con.execute(f"insert or replace into users values ({', '.join('?' * len(COLUMNS))})",
                    [record[c] for c in COLUMNS])


def _get(username: str) -> dict | None:
    """Full record including the hash (internal use only)."""
    df = _read()
    rows = df[df["username"] == (username or "").strip().lower()]
    return rows.iloc[0].to_dict() if len(rows) else None


def _require(username: str) -> dict:
    user = _get(username)
    if user is None:
        raise UserError(f"No user named {username!r}.")
    return user


# --- Public API -------------------------------------------------------------------

def get_user(username: str) -> dict | None:
    """User record without the password hash, or None."""
    user = _get(username)
    return None if user is None else {c: user[c] for c in PUBLIC_COLUMNS}


def list_users(status: str | None = None) -> pd.DataFrame:
    """All users (optionally one status), without password hashes, oldest first."""
    df = _read()
    if status:
        df = df[df["status"] == status]
    return df[PUBLIC_COLUMNS].sort_values("created_at").reset_index(drop=True)


def create_request(name, email, username, password, confirm, requested_role, requested_team="",
                   reason="", reserved=()) -> list[str]:
    """Validate and save an access request as 'pending'. Returns the problems found;
    nothing is saved unless the list is empty. `reserved` holds usernames that are
    taken outside the store (the break-glass admin)."""
    username = (username or "").strip().lower()
    problems = []
    if not (name or "").strip():
        problems.append("Enter your name.")
    if not EMAIL_RE.match((email or "").strip()):
        problems.append("Enter a valid email address.")
    if not USERNAME_RE.match(username):
        problems.append("Username must be 3-32 characters: letters, numbers, '.', '_' or '-'.")
    elif username in {r.strip().lower() for r in reserved} or _get(username) is not None:
        problems.append("That username is already taken.")
    problems += password_problems(password, confirm)
    if requested_role not in REQUESTABLE_ROLES:
        problems.append("Requested role must be supervisor or viewer.")
    if requested_role == "supervisor" and not (requested_team or "").strip():
        problems.append("Choose your team (required for supervisors).")
    if problems:
        return problems
    now = _now()
    _write({"username": username, "name": name.strip(), "email": email.strip(),
            "role": "", "team": "", "password_hash": hash_password(password), "status": "pending",
            "must_change_password": False, "requested_role": requested_role,
            "requested_team": requested_team if requested_role == "supervisor" else "",
            "reason": (reason or "").strip(), "created_at": now, "updated_at": now})
    return []


def _check_role(role, team):
    if role not in ROLES:
        raise UserError(f"Unknown role {role!r}.")
    if role == "supervisor" and not team:
        raise UserError("A supervisor needs a team.")


def approve(username, role, team, actor):
    """Activate a pending request with the role and team the admin chose."""
    user = _require(username)
    if user["status"] != "pending":
        raise UserError("Only pending requests can be approved.")
    _check_role(role, team)
    now = _now()
    _write({**user, "role": role, "team": team if role == "supervisor" else "", "status": "active",
            "approved_by": actor, "approved_at": now, "updated_at": now})


def reject(username, actor):
    user = _require(username)
    if user["status"] != "pending":
        raise UserError("Only pending requests can be rejected.")
    now = _now()
    _write({**user, "status": "rejected", "approved_by": actor, "approved_at": now, "updated_at": now})


def set_role(username, role, team, actor):
    """Change an active user's role and team. An admin can't demote themselves."""
    user = _require(username)
    _check_role(role, team)
    if user["username"] == (actor or "").lower() and role != "admin":
        raise UserError("You can't remove your own admin role.")
    _write({**user, "role": role, "team": team if role == "supervisor" else "",
            "updated_at": _now()})


def deactivate(username, actor):
    user = _require(username)
    if user["username"] == (actor or "").lower():
        raise UserError("You can't deactivate your own account.")
    if user["status"] != "active":
        raise UserError("Only active users can be deactivated.")
    _write({**user, "status": "deactivated", "updated_at": _now()})


def reactivate(username, actor):
    user = _require(username)
    if user["status"] != "deactivated":
        raise UserError("Only deactivated users can be reactivated.")
    _write({**user, "status": "active", "updated_at": _now()})


def set_password(username, new_password, must_change_password=False):
    """Store a new bcrypt hash (the caller validates the password rules)."""
    user = _require(username)
    _write({**user, "password_hash": hash_password(new_password),
            "must_change_password": must_change_password, "updated_at": _now()})


def reset_password(username, actor) -> str:
    """Set a random temporary password that must be changed at next sign-in.
    Returns it so the admin can pass it on; it is not stored in plain text."""
    _require(username)
    temp = temporary_password()
    set_password(username, temp, must_change_password=True)
    return temp


def change_password(username, current, new, confirm) -> list[str]:
    """Self-service change. Returns problems; saves only when there are none."""
    user = _require(username)
    if not check_password(current, user["password_hash"]):
        return ["Current password is incorrect."]
    problems = password_problems(new, confirm)
    if not problems and new == current:
        problems.append("The new password must be different from the current one.")
    if not problems:
        set_password(username, new, must_change_password=False)
    return problems


def authenticate(username, password, admin=None) -> tuple[dict | None, str | None]:
    """Check credentials. Returns (session user, None) or (None, reason) where reason
    is 'incorrect', 'pending' or 'inactive'. `admin` is the break-glass admin from
    secrets (username, name, password_hash); it is checked before the store is
    touched, so it works when the store is down. Other store errors propagate."""
    username = (username or "").strip().lower()
    if admin and username == str(admin.get("username", "")).strip().lower():
        if check_password(password, admin.get("password_hash", "")):
            return {"username": username, "name": admin.get("name") or username, "role": "admin",
                    "team": "", "must_change_password": False, "break_glass": True}, None
        return None, "incorrect"
    user = _get(username)
    if user is None or not check_password(password, user["password_hash"]):
        return None, "incorrect"
    if user["status"] == "pending":
        return None, "pending"
    if user["status"] != "active":
        return None, "inactive"
    return session_user(user), None


def session_user(user: dict) -> dict:
    """The fields kept in session_state for a signed-in store user."""
    return {"username": user["username"], "name": user["name"] or user["username"],
            "role": user["role"], "team": user["team"],
            "must_change_password": bool(user["must_change_password"]), "break_glass": False}
