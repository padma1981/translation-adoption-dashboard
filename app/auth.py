"""Sign-in, access requests, password changes and role-based page access.

The entry point calls gate() before drawing anything else; until a user is signed
in only the sign-in screens are shown (no menu, no filters). User records are
read and written only through src.users.
"""

import time

import streamlit as st

import ui
from src import users

LOCKOUT_ATTEMPTS = 5
LOCKOUT_SEC = 5 * 60
MAX_REQUESTS = 3
USER_REFRESH_SEC = 60          # re-read the signed-in user's record at most this often
DEFAULT_TIMEOUT_MIN = 480
# Survive sign-out, so signing out doesn't reset the lockout or request limits.
KEEP_ON_SIGN_OUT = ("_failed_logins", "_locked_until", "_requests_sent")

PAGE_ACCESS = {
    "admin": {"overview", "agents", "languages", "operational", "cost", "data_quality",
              "user_management"},
    "supervisor": {"overview", "agents", "languages", "operational", "cost"},
    "viewer": {"overview"},
}
DENIED = "You don't have access to this page."
INCORRECT = "Incorrect username or password"
NOT_ACTIVE_YET = "Your account is not active yet"
NOT_ACTIVE = "Your account is not active"


# --- Config and session ----------------------------------------------------------

def config() -> dict | None:
    """[auth] secrets, or None when they are missing or incomplete."""
    try:
        auth = st.secrets["auth"]
        admin = dict(auth["admin"])
    except Exception:   # no secrets file, or no [auth] / [auth.admin] block
        return None
    if not admin.get("username") or not admin.get("password_hash"):
        return None
    return {"timeout_min": float(auth.get("session_timeout_minutes", DEFAULT_TIMEOUT_MIN)),
            "admin": admin}


def allowed_pages(user) -> set:
    return PAGE_ACCESS.get((user or {}).get("role"), set())


def sign_in(user):
    ss = st.session_state
    ss.user = user
    ss.signed_in_at = ss._user_checked_at = time.time()
    ss._failed_logins = 0


def sign_out(notice=None):
    """Clear session_state (keeping the lockout and request counters)."""
    ss = st.session_state
    keep = {k: ss[k] for k in KEEP_ON_SIGN_OUT if k in ss}
    ss.clear()
    ss.update(keep)
    if notice:
        ss._auth_notice = notice


def current_user(cfg) -> dict | None:
    """The signed-in user, after applying the session timeout and picking up
    role/team/status changes an admin made since sign-in."""
    ss = st.session_state
    user = ss.get("user")
    if not user:
        return None
    now = time.time()
    if now - ss.get("signed_in_at", 0) > cfg["timeout_min"] * 60:
        sign_out("Your session expired. Please sign in again.")
        return None
    if not user.get("break_glass") and now - ss.get("_user_checked_at", 0) > USER_REFRESH_SEC:
        try:
            record = users.get_user(user["username"])
        except Exception:   # store unavailable: keep the session as it is
            return user
        if record is None or record["status"] != "active":
            sign_out(NOT_ACTIVE)
            return None
        ss.user = users.session_user(record)
        ss._user_checked_at = now
    return ss.user


def gate(make_pages) -> dict:
    """Return the signed-in user, or draw the setup / sign-in / change-password
    screen and stop. make_pages(visible=set()) gives the app's pages, registered
    hidden here so a deep link keeps its URL through sign-in."""
    cfg = config()
    user = None
    if cfg is None:
        screen = setup_screen
    else:
        user = current_user(cfg)
        if user is None:
            screen = sign_in_screen
        elif user["must_change_password"] or st.session_state.get("_show_change_password"):
            screen = change_password_screen
        else:
            return user
    st.navigation([st.Page(screen, title="Sign in", default=True),
                   *make_pages(visible=set(), with_default=False).values()], position="hidden")
    screen()
    st.stop()


# --- Screens ------------------------------------------------------------------------

def _heading(subtitle):
    st.title("Translation Tool Adoption", text_alignment="center", anchor=False)
    st.subheader(subtitle, text_alignment="center", anchor=False)


def setup_screen():
    _heading("Sign-in isn't set up yet")
    st.warning(
        "No `[auth]` secrets are configured, so the dashboard can't open.\n\n"
        "1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (it is git-ignored).\n"
        "2. Run `python scripts/hash_password.py` and paste the hash into `[auth.admin]` "
        "`password_hash`; set `username` and `name`.\n"
        "3. Restart the app and sign in as that admin.\n\n"
        "Without a `[connections.gsheets]` block, other users are kept in a local SQLite file "
        "(`data/users/users.db`). On Streamlit Community Cloud paste the secrets under "
        "Manage app → Settings → Secrets.", icon="🔐")


def sign_in_screen():
    ss = st.session_state
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        if ss.get("_auth_view") == "request":
            request_access_form()
            return
        _heading("Sign in")
        if notice := ss.pop("_auth_notice", None):
            st.info(notice)
        locked_for = ss.get("_locked_until", 0) - time.time()
        if locked_for > 0:
            minutes = int(locked_for // 60) + 1
            st.error(f"Too many failed attempts. Try again in {minutes} minute"
                     f"{'s' if minutes > 1 else ''}.")
            return
        with st.form("sign_in"):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            _try_sign_in(username, password)
        if st.button("Request access", type="tertiary", key="request_access_link"):
            ss._auth_view = "request"
            st.rerun()


def _try_sign_in(username, password):
    ss = st.session_state
    try:
        user, problem = users.authenticate(username, password, config()["admin"])
    except Exception:
        st.error("Sign-in is unavailable right now (the user store can't be reached). "
                 "Try again later.")
        return
    if problem == "incorrect":
        ss._failed_logins = ss.get("_failed_logins", 0) + 1
        if ss._failed_logins >= LOCKOUT_ATTEMPTS:
            ss._locked_until = time.time() + LOCKOUT_SEC
            ss._failed_logins = 0
            st.rerun()
        st.error(INCORRECT)
    elif problem == "pending":
        st.error(NOT_ACTIVE_YET)
    elif problem == "inactive":
        st.error(NOT_ACTIVE)
    else:
        sign_in(user)
        st.rerun()


def request_access_form():
    ss = st.session_state
    _heading("Request access")
    if st.button("← Back to sign in", type="tertiary", key="back_to_sign_in"):
        ss._auth_view = "sign_in"
        st.rerun()
    if ss.pop("_request_sent", False):
        st.success("Request sent. An admin will review it.")
    if ss.get("_requests_sent", 0) >= MAX_REQUESTS:
        st.info(f"You've sent {MAX_REQUESTS} requests in this session. An admin will review them.")
        return
    teams = ui.options()["teams"]
    with st.form("request_access"):
        name = st.text_input("Name")
        email = st.text_input("Email")
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="new-password",
                                 help=f"At least {users.MIN_PASSWORD_LEN} characters, with letters "
                                      "and numbers.")
        confirm = st.text_input("Confirm password", type="password", autocomplete="new-password")
        role = st.selectbox("Requested role", users.REQUESTABLE_ROLES,
                            help="Supervisors see their own team; viewers see the Overview only.")
        team = st.selectbox("Team (required for supervisors)", teams, index=None,
                            placeholder="Choose your team")
        reason = st.text_area("Reason", placeholder="Why do you need access?")
        submitted = st.form_submit_button("Send request", type="primary", width="stretch")
    if submitted:
        try:
            problems = users.create_request(name, email, username, password, confirm, role,
                                            team or "", reason,
                                            reserved=[config()["admin"]["username"]])
        except Exception:
            problems = ["Requests can't be saved right now. Try again later."]
        for p in problems:
            st.error(p)
        if not problems:
            ss._requests_sent = ss.get("_requests_sent", 0) + 1
            ss._request_sent = True
            st.rerun()


def change_password_screen():
    ss = st.session_state
    user = ss.user
    forced = user["must_change_password"]
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _heading("Change password")
        if user.get("break_glass"):
            st.info("This is the break-glass admin from the app's secrets. Change its password by "
                    "running `python scripts/hash_password.py` and replacing `password_hash` under "
                    "`[auth.admin]` in the secrets (Manage app → Settings → Secrets on Streamlit "
                    "Cloud).")
        else:
            if forced:
                st.warning("You're using a temporary password. Choose a new one to continue.")
            with st.form("change_password", clear_on_submit=True):
                current = st.text_input("Current password", type="password",
                                        autocomplete="current-password")
                new = st.text_input("New password", type="password", autocomplete="new-password",
                                    help=f"At least {users.MIN_PASSWORD_LEN} characters, with "
                                         "letters and numbers; different from the current one.")
                confirm = st.text_input("Confirm new password", type="password",
                                        autocomplete="new-password")
                submitted = st.form_submit_button("Change password", type="primary",
                                                  width="stretch")
            if submitted:
                try:
                    problems = users.change_password(user["username"], current, new, confirm)
                except Exception:
                    problems = ["Passwords can't be changed right now. Try again later."]
                for p in problems:
                    st.error(p)
                if not problems:
                    ss.user = {**user, "must_change_password": False}
                    ss._show_change_password = False
                    ss._auth_notice = "Password changed."
                    st.rerun()
        if forced:
            st.button("Sign out", on_click=sign_out, key="sign_out_forced")
        elif st.button("Back to the dashboard", type="tertiary", key="cancel_change_password"):
            ss._show_change_password = False
            st.rerun()


def user_bar(user):
    """Top-right: who is signed in, Change password and Sign out."""
    ss = st.session_state
    if notice := ss.pop("_auth_notice", None):
        st.toast(notice, icon="✅")
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                      key="user_bar"):
        st.markdown(f"Signed in as **{user['name']}** ({user['role']})", width="content")
        if st.button("Change password", key="change_password_button", type="tertiary"):
            ss._show_change_password = True
            st.rerun()
        st.button("Sign out", key="sign_out_button", on_click=sign_out)
