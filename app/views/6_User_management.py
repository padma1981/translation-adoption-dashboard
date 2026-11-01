"""User management (admin only): review access requests, change roles and teams,
deactivate or reactivate users, and reset passwords. All changes go through src.users."""

import streamlit as st

import ui
from src import users

ss = st.session_state
me = ss.user
if me["role"] != "admin":   # the entry point already blocks this; kept as a second check
    st.error("You don't have access to this page.", icon="🔒")
    st.stop()

st.title("User management")
TEAMS = ui.options()["teams"]
SHOWN = ["username", "name", "email", "role", "team", "status", "must_change_password",
         "created_at", "approved_by", "approved_at", "updated_at"]


def act(action, *args, done):
    """Run a users.* change and queue a confirmation. Returns its result (True if it
    returns nothing), or None after showing why it failed."""
    try:
        result = action(*args)
    except users.UserError as e:
        st.error(str(e))
        return None
    except Exception:
        st.error("The user store can't be reached right now. Try again later.")
        return None
    ss._um_notice = done
    return True if result is None else result


def role_team_inputs(key, role, team):
    """Role and team selectors; team only matters for supervisors."""
    c1, c2 = st.columns(2)
    role = c1.selectbox("Role", users.ROLES, index=users.ROLES.index(role) if role in users.ROLES
                        else users.ROLES.index("viewer"), key=f"role_{key}")
    team = c2.selectbox("Team (supervisors)", TEAMS, index=TEAMS.index(team) if team in TEAMS else None,
                        placeholder="Choose a team", key=f"team_{key}",
                        disabled=role != "supervisor")
    return role, team or ""


if notice := ss.pop("_um_notice", None):
    st.success(notice)
if temp := ss.pop("_um_temp_password", None):
    st.warning(f"Temporary password for **{temp[0]}**: `{temp[1]}`  \n"
               "It is shown only this once. Pass it on securely; they must change it when they "
               "sign in.", icon="🔑")

try:
    everyone = users.list_users()
except Exception:
    st.error("The user store can't be reached right now. The break-glass admin still works; "
             "try again later.")
    st.stop()

# --- Pending requests -------------------------------------------------------------
pending = everyone[everyone["status"] == "pending"]
st.subheader(f"Pending requests ({len(pending)})", anchor=False)
if pending.empty:
    st.caption("No requests waiting.")
for r in pending.itertuples():
    with st.container(border=True, key=f"request_{r.username}"):
        st.markdown(f"**{r.name}** · `{r.username}` · {r.email}  \n"
                    f"Requested **{r.requested_role}**"
                    + (f" for team **{r.requested_team}**" if r.requested_team else "")
                    + f" · {r.created_at}")
        if r.reason:
            st.caption(f"Reason: {r.reason}")
        role, team = role_team_inputs(f"req_{r.username}", r.requested_role, r.requested_team)
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Approve", key=f"approve_{r.username}", type="primary", width="stretch"):
            if act(users.approve, r.username, role, team, me["username"],
                   done=f"Approved {r.username} as {role}."):
                st.rerun()
        if c2.button("Reject", key=f"reject_{r.username}", width="stretch"):
            if act(users.reject, r.username, me["username"], done=f"Rejected {r.username}."):
                st.rerun()

# --- All users --------------------------------------------------------------------
st.subheader("All users", anchor=False)
st.caption(f"The break-glass admin (`{me['username']}`) lives in the app's secrets, not here."
           if me.get("break_glass") else "The break-glass admin lives in the app's secrets, not here.")
st.dataframe(everyone[SHOWN], hide_index=True, width="stretch")

managed = everyone[everyone["status"].isin(["active", "deactivated"])]
if managed.empty:
    st.caption("No approved users yet.")
    st.stop()
name = st.selectbox("Manage user", managed["username"],
                    format_func=lambda u: f"{u} ({managed.set_index('username').loc[u, 'status']})",
                    key="manage_user")
u = managed.set_index("username").loc[name]
is_me = name == me["username"]
with st.container(border=True, key="manage_card"):
    st.markdown(f"**{u['name']}** · {u['email']} · {u['role']}"
                + (f" ({u['team']})" if u["team"] else "") + f" · {u['status']}")
    if is_me:
        st.caption("This is you: you can't deactivate yourself or remove your own admin role.")
    role, team = role_team_inputs(f"user_{name}", u["role"], u["team"])
    c1, c2, c3 = st.columns(3)
    if c1.button("Save role and team", key="save_role", width="stretch"):
        if act(users.set_role, name, role, team, me["username"], done=f"Updated {name}: {role}."):
            st.rerun()
    if u["status"] == "active":
        if c2.button("Deactivate", key="deactivate", width="stretch", disabled=is_me):
            if act(users.deactivate, name, me["username"], done=f"Deactivated {name}."):
                st.rerun()
    elif c2.button("Reactivate", key="reactivate", width="stretch"):
        if act(users.reactivate, name, me["username"], done=f"Reactivated {name}."):
            st.rerun()
    if c3.button("Reset password", key="reset_password", width="stretch"):
        temp = act(users.reset_password, name, me["username"], done=f"Password reset for {name}.")
        if temp:
            ss._um_temp_password = (name, temp)
            st.rerun()
