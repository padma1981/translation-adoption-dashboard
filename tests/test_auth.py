"""Sign-in gate, access requests, roles and passwords in the running app (AppTest),
using the SQLite user store."""

import time

import pytest

from src import users
from tests.conftest import ADMIN_PASSWORD, ADMIN_SESSION, new_app, signed_in

GOOD = "Correct1horse"
DATA_PAGES = [None, "views/1_Agents_and_Teams.py", "views/2_Languages.py",
              "views/3_Operational_Impact.py", "views/4_Cost.py"]
DQ = "views/5_Data_Quality.py"
UM = "views/6_User_management.py"


# --- Helpers -----------------------------------------------------------------------

def field(at, label):
    return next(w for w in at.text_input if w.label == label)


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    return at


def sign_in(at, username, password):
    field(at, "Username").input(username)
    field(at, "Password").input(password)
    return click(at, "Sign in")


def errors(at):
    return [e.value for e in at.error]


def in_app(at):
    return "Adoption Percentage" in [h.value for h in at.subheader]


def make_user(username="sam", role="supervisor", team="Atlas", password=GOOD, status="active"):
    assert users.create_request("Sam Lee", f"{username}@example.com", username, password, password,
                                "viewer" if role == "admin" else role, team, "Demo") == []
    if status == "active":
        users.approve(username, role, team, actor="admin")
    elif status == "rejected":
        users.reject(username, actor="admin")
    return username


def session_of(username):
    return users.session_user(users._get(username))


# --- Gate ---------------------------------------------------------------------------

def test_setup_message_when_secrets_missing():
    at = new_app(auth=None).run()
    assert not at.exception
    assert any("No `[auth]` secrets are configured" in w.value for w in at.warning)
    assert not in_app(at) and not at.text_input


def test_sign_in_screen_comes_first_without_menu_or_filters():
    at = new_app().run()
    assert not at.exception
    assert [h.value for h in at.subheader] == ["Sign in"]
    assert [w.label for w in at.text_input] == ["Username", "Password"]
    assert not at.selectbox and not at.get("plotly_chart")
    at.switch_page("views/4_Cost.py").run()   # a deep link still gets the sign-in screen
    assert [h.value for h in at.subheader] == ["Sign in"]


def test_correct_and_incorrect_sign_in():
    at = new_app().run()
    sign_in(at, "admin", "Wrong123456")
    assert errors(at) == ["Incorrect username or password"]
    sign_in(at, "nobody", ADMIN_PASSWORD)
    assert errors(at) == ["Incorrect username or password"]   # never says which one is wrong
    sign_in(at, "admin", ADMIN_PASSWORD)
    assert not at.exception and in_app(at)
    assert any(m.value == "Signed in as **Test Admin** (admin)" for m in at.markdown)


def test_lockout_after_five_failures():
    make_user()
    at = new_app().run()
    for _ in range(4):
        sign_in(at, "sam", "Wrong123456")
    assert errors(at) == ["Incorrect username or password"]
    sign_in(at, "sam", "Wrong123456")
    assert errors(at) == ["Too many failed attempts. Try again in 5 minutes."]
    assert not at.text_input   # no form while blocked, so the right password can't be tried
    at.session_state["_locked_until"] = time.time() - 1   # 5 minutes later
    at.run()
    sign_in(at, "sam", GOOD)
    assert in_app(at)


@pytest.mark.parametrize("status, message", [("pending", "Your account is not active yet"),
                                             ("rejected", "Your account is not active")])
def test_inactive_statuses_cannot_sign_in(status, message):
    make_user(status=status)
    at = sign_in(new_app().run(), "sam", GOOD)
    assert errors(at) == [message] and not in_app(at)


def test_deactivate_blocks_sign_in():
    make_user()
    users.deactivate("sam", actor="admin")
    at = sign_in(new_app().run(), "sam", GOOD)
    assert errors(at) == ["Your account is not active"]


def test_deactivation_ends_an_open_session():
    make_user()
    at = signed_in(new_app(), session_of("sam")).run()
    assert in_app(at)
    users.deactivate("sam", actor="admin")
    at.session_state["_user_checked_at"] = 0   # next refresh is due
    at.run()
    assert [h.value for h in at.subheader] == ["Sign in"]


def test_session_timeout_returns_to_sign_in():
    at = signed_in(new_app()).run()
    assert in_app(at)
    at.session_state["signed_in_at"] = time.time() - 481 * 60
    at.run()
    assert [h.value for h in at.subheader] == ["Sign in"]
    assert any("session expired" in i.value for i in at.info)


def test_sign_out_clears_session_state():
    at = signed_in(new_app(), dict(ADMIN_SESSION)).run()
    at.session_state["teams"] = ["Echo"]
    at.run()
    at.button(key="sign_out_button").click().run()
    assert [h.value for h in at.subheader] == ["Sign in"]
    assert "user" not in at.session_state and "teams" not in at.session_state


# --- Request access -------------------------------------------------------------------

def fill_request(at, username="maria", password=GOOD, role="supervisor", team="Echo"):
    for label, value in [("Name", "Maria Lopez"), ("Email", "maria@example.com"),
                         ("Username", username), ("Password", password),
                         ("Confirm password", password)]:
        field(at, label).input(value)
    next(s for s in at.selectbox if s.label == "Requested role").set_value(role)
    next(s for s in at.selectbox if s.label.startswith("Team")).set_value(team)
    next(t for t in at.text_area if t.label == "Reason").input("Coach my team")
    return click(at, "Send request")


def test_request_access_form_saves_pending_request():
    at = click(new_app().run(), "Request access")
    assert [h.value for h in at.subheader] == ["Request access"]
    assert next(s for s in at.selectbox if s.label == "Requested role").options == \
        ["supervisor", "viewer"]   # admin can't be requested
    fill_request(at)
    assert not at.exception
    assert [s.value for s in at.success] == ["Request sent. An admin will review it."]
    user = users.get_user("maria")
    assert user["status"] == "pending" and user["requested_team"] == "Echo"


def test_request_access_form_shows_validation_errors():
    at = click(new_app().run(), "Request access")
    fill_request(at, username="Admin", password="short")   # break-glass name is taken too
    assert "That username is already taken." in errors(at)
    assert any("at least 10 characters" in e for e in errors(at))
    assert users.list_users().empty


def test_at_most_three_requests_per_session():
    at = click(new_app().run(), "Request access")
    for name in ("maria1", "maria2", "maria3"):
        fill_request(at, username=name)
    assert len(users.list_users("pending")) == 3
    assert any("3 requests in this session" in i.value for i in at.info)
    assert not at.text_input


# --- Admin: user management ------------------------------------------------------------

def test_approve_in_user_management_then_sign_in():
    assert users.create_request("Maria Lopez", "maria@example.com", "maria", GOOD, GOOD,
                                "supervisor", "Echo", "Coach my team") == []
    at = signed_in(new_app()).run()
    at.switch_page(UM).run()
    assert not at.exception, at.exception
    assert "Pending requests (1)" in [h.value for h in at.subheader]
    at.button(key="approve_maria").click().run()
    assert not at.exception
    assert users.get_user("maria")["status"] == "active"
    assert users.get_user("maria")["team"] == "Echo" and users.get_user("maria")["approved_by"] == "admin"
    at = sign_in(new_app().run(), "maria", GOOD)
    assert in_app(at)


def test_reject_in_user_management():
    make_user(status="pending")
    at = signed_in(new_app()).run()
    at.switch_page(UM).run()
    at.button(key="reject_sam").click().run()
    assert users.get_user("sam")["status"] == "rejected"


def test_admin_cannot_deactivate_themselves_in_user_management():
    make_user("boss", role="admin", team="")
    at = signed_in(new_app(), session_of("boss")).run()
    at.switch_page(UM).run()
    assert not at.exception, at.exception
    at.selectbox(key="manage_user").set_value("boss").run()
    assert at.button(key="deactivate").disabled
    at.selectbox(key="role_user_boss").set_value("viewer").run()
    at.button(key="save_role").click().run()
    assert any("own admin role" in e for e in errors(at))
    assert users.get_user("boss")["role"] == "admin"


def test_reset_password_shows_temporary_password_once():
    make_user()
    at = signed_in(new_app()).run()
    at.switch_page(UM).run()
    at.button(key="reset_password").click().run()
    shown = [w.value for w in at.warning if "Temporary password" in w.value]
    assert len(shown) == 1
    temp = shown[0].split("`")[1]
    assert users.authenticate("sam", temp)[0]["must_change_password"] is True
    at.run()
    assert not [w for w in at.warning if "Temporary password" in w.value]


# --- Passwords ------------------------------------------------------------------------------

def change(at, current, new, confirm=None):
    field(at, "Current password").input(current)
    field(at, "New password").input(new)
    field(at, "Confirm new password").input(new if confirm is None else confirm)
    return click(at, "Change password")


def test_temporary_password_forces_a_change():
    make_user()
    temp = users.reset_password("sam", actor="admin")
    at = sign_in(new_app().run(), "sam", temp)
    assert [h.value for h in at.subheader] == ["Change password"] and not in_app(at)
    at.switch_page("views/4_Cost.py").run()   # can't get around it
    assert [h.value for h in at.subheader] == ["Change password"]
    change(at, temp, temp)
    assert any("different" in e for e in errors(at))
    change(at, temp, "Brandnew123")
    assert not at.exception and not errors(at)
    assert users.authenticate("sam", "Brandnew123")[0]["must_change_password"] is False


def test_change_password_requires_correct_current_password():
    make_user()
    at = signed_in(new_app(), session_of("sam")).run()
    at.button(key="change_password_button").click().run()
    change(at, "Wrong123456", "Brandnew123")
    assert errors(at) == ["Current password is incorrect."]
    change(at, GOOD, "Brandnew123")
    assert in_app(at)
    assert users.authenticate("sam", "Brandnew123")[1] is None


def test_break_glass_admin_change_password_screen_points_to_secrets():
    at = signed_in(new_app()).run()
    at.button(key="change_password_button").click().run()
    assert any("hash_password.py" in i.value for i in at.info)
    assert not at.text_input


def test_break_glass_admin_works_when_store_unavailable(monkeypatch):
    at = new_app().run()

    def unavailable(*a, **k):
        raise ConnectionError("Google Sheets unreachable")
    monkeypatch.setattr(users, "_read", unavailable)
    sign_in(at, "sam", GOOD)
    assert any("can't be reached" in e for e in errors(at))
    sign_in(at, "admin", ADMIN_PASSWORD)
    assert not at.exception and in_app(at)
    at.switch_page(UM).run()
    assert not at.exception
    assert any("can't be reached" in e for e in errors(at))


# --- Roles -------------------------------------------------------------------------------------

def test_page_access_by_role():
    from auth import PAGE_ACCESS   # app/ is on sys.path once the app has run
    assert PAGE_ACCESS["supervisor"] == {"overview", "agents", "languages", "operational", "cost"}
    assert PAGE_ACCESS["viewer"] == {"overview"}
    assert {"data_quality", "user_management"} <= PAGE_ACCESS["admin"]


def test_supervisor_scope_forces_their_team_in_every_metrics_call(monkeypatch):
    make_user()   # supervisor of Atlas (Rachel Young)
    at = signed_in(new_app(), session_of("sam")).run()
    import ui
    calls = []
    original = ui._cached

    def spy(fn_name, filter_args, extra, version):
        calls.append((fn_name, tuple(filter_args[2] or ()), tuple(filter_args[3] or ())))
        return original(fn_name, filter_args, extra, version)
    monkeypatch.setattr(ui, "_cached", spy)

    for page in DATA_PAGES:
        calls.clear()
        at.session_state["teams"] = ["Echo", "Delta"]   # tampered filter state
        at.session_state["supervisors"] = ["Cynthia Reyes"]
        if page:
            at.switch_page(page)
        at.run()
        assert not at.exception, (page, at.exception)
        assert calls, page
        assert {(teams, sups) for _, teams, sups in calls} == {(("Atlas",), ("Rachel Young",))}, page
        assert at.session_state["teams"] == ["Atlas"]
        assert at.session_state["supervisors"] == ["Rachel Young"]
    locked = [at.multiselect(key="_w_teams"), at.multiselect(key="_w_supervisors")]
    assert [m.value for m in locked] == [["Atlas"], ["Rachel Young"]]
    assert all(m.disabled for m in locked) and not at.multiselect(key="_w_languages").disabled
    # The locked team doesn't count as a changed filter; the summary names it.
    assert [p.proto.popover.label for p in at.get("popover")] == ["Filters"]
    assert any("Atlas · Rachel Young · All languages" in m.value for m in at.markdown)


@pytest.mark.parametrize("page", [DQ, UM])
def test_supervisor_cannot_open_data_quality_or_user_management(page):
    make_user()
    at = signed_in(new_app(), session_of("sam")).run()
    at.switch_page(page).run()
    assert not at.exception
    assert errors(at) == ["You don't have access to this page."]
    assert not at.get("plotly_chart") and not at.get("download_button")


def test_viewer_sees_only_the_overview_donut():
    make_user("vic", role="viewer", team="")
    at = signed_in(new_app(), session_of("vic")).run()
    assert not at.exception, at.exception
    assert [h.value for h in at.subheader] == ["Adoption Percentage"]   # no Trends
    assert len(at.get("plotly_chart")) == 1
    downloads = at.get("download_button")
    assert len(downloads) == 1 and downloads[0].proto.label == "Download CSV"
    assert not [m for m in at.markdown if "missed calls" in m.value]
    for page in DATA_PAGES[1:] + [DQ, UM]:
        at.switch_page(page).run()
        assert errors(at) == ["You don't have access to this page."], page
        assert not at.get("download_button"), page
