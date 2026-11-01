"""Data Quality: session linking, pre-enablement sessions, missing proficiency, orphans."""

import plotly.express as px
import streamlit as st

import ui
from ui import metrics

f = ui.page_header("Data Quality",
                   "Session counts use the session date and source language; interpreter orphans "
                   "have no date, team or language so they are never filtered.",
                   require_data=False)

summary = ui.q(metrics.dq_summary, f).set_index("metric")["value"]
cards = [  # (dq_summary metric, short label, explanation)
    ("Sessions linked by call_id", "Linked by call_id", "Session row carried the call_id."),
    ("Sessions linked by time window", "Linked by time window",
     "call_id was blank; matched to the agent's call that contained the session start."),
    ("Unlinked practice sessions", "Unlinked practice", "No call matched; not counted toward adoption."),
    ("Ambiguous time-window links", "Ambiguous links",
     "More than one candidate call; the closest start was used."),
    ("Sessions before tool_enabled_date", "Before enablement",
     "Sessions dated before the agent's tool_enabled_date; excluded from adoption."),
    ("Native optional-use sessions", "Native optional use",
     "Native speaker used the tool on their own language; never counts for or against adoption."),
    ("Agents with no language records", "No language records",
     "Agents with no proficiency record for any selected language; treated as 'none'."),
    ("Orphan interpreter rows (unfiltered)", "Orphan interpreter rows",
     "Interpreter rows whose call_id is not in fact_call. Not filtered."),
]
grid = st.columns(4) + st.columns(4)
for col, (name, label, help_text) in zip(grid, cards):
    col.metric(label, ui.num(summary.get(name, 0)), border=True, help=help_text)
missing_calls = int(summary.get("Sessions whose call_id is not in fact_call", 0))
if missing_calls:
    st.warning(f"{missing_calls:,} sessions carry a call_id that is not in fact_call.")

st.subheader("Session linking")
links = ui.q(metrics.dq_session_links, f)
if links["sessions"].sum() == 0:
    ui.no_data("translation sessions")
else:
    labels = {"call_id": "By call_id", "time_window": "By time window", "unlinked": "Unlinked"}
    links["Method"] = links["link_method"].map(labels)
    links["share"] = links["sessions"] / links["sessions"].sum()
    fig = px.bar(links, x="sessions", y="Method", orientation="h", text="share", color="Method",
                 color_discrete_map=dict(zip(labels.values(), ["#2a78d6", "#6250d6", "#a3a29b"])),
                 category_orders={"Method": list(labels.values())})
    fig.update_traces(texttemplate="%{text:.1%}", textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}: %{x:,} sessions")
    fig = ui.style(fig, height=230, legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(tickformat=",", range=[0, links["sessions"].max() * 1.12])
    fig.update_yaxes(title_text="", gridcolor="rgba(0,0,0,0)")
    ui.show(fig)
    st.caption("About 10% of sessions are logged without a call_id; they are linked by agent and time.")

left, right = st.columns(2)
with left:
    st.markdown("**Sessions before the agent's tool was enabled**")
    early = ui.q(metrics.dq_sessions_before_enablement, f)
    if early.empty:
        st.success("None in this selection.")
    else:
        st.dataframe(early[["agent_name", "team", "session_start_ts", "source_language",
                            "tool_enabled_date"]].rename(columns={
                                "agent_name": "Agent", "team": "Team", "session_start_ts": "Session start",
                                "source_language": "Language", "tool_enabled_date": "Enabled"}),
                     hide_index=True, width="stretch", height=260)
with right:
    st.markdown("**Agents with no language records**")
    missing = ui.q(metrics.dq_agents_without_language_records, f)
    if missing.empty:
        st.success("None in this selection.")
    else:
        st.dataframe(missing[["agent_id", "agent_name", "team", "site"]].rename(columns={
            "agent_id": "Agent ID", "agent_name": "Agent", "team": "Team", "site": "Site"}),
            hide_index=True, width="stretch", height=260)

st.markdown("**Orphan interpreter rows** (not filtered)")
orphans = ui.q(metrics.dq_orphan_interpreter_rows, f)
if orphans.empty:
    st.success("Every interpreter row matches a call.")
else:
    st.dataframe(orphans, hide_index=True, width="stretch", height=220)

ui.footnote()
