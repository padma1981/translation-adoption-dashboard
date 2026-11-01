"""Agents & Teams: rates by team, supervisor and site; ramp curve; leaderboard."""

import plotly.express as px
import streamlit as st

import ui
from ui import metrics

f = ui.page_header("Agents & Teams")
rate_cols = list(ui.RATE_LABELS)


def rates_by(by, label):
    """Grouped bars of the three rates for one dimension, plus call counts in the hover."""
    df = ui.q(metrics.adoption_by, f, by=by)
    if by == "supervisor":
        df[by] = df["supervisor"] + " (" + df["team"] + ")"
    long = df.melt(id_vars=[by, "eligible_calls"], value_vars=rate_cols,
                   var_name="rate", value_name="value")
    long["Rate"] = long["rate"].map(ui.RATE_LABELS)
    fig = px.bar(long, y=by, x="value", color="Rate", barmode="group", orientation="h",
                 color_discrete_map={ui.RATE_LABELS[r]: ui.RATE_COLORS[r] for r in rate_cols},
                 custom_data=["eligible_calls"], labels={by: label})
    fig.update_traces(hovertemplate="%{x:.1%} (%{customdata[0]:,} eligible calls)")
    fig = ui.style(fig, height=max(260, 70 * len(df) + 80))
    fig.update_layout(hovermode="y unified", bargap=0.25)
    fig.update_xaxes(tickformat=".0%", range=[0, 1], gridcolor="rgba(128,128,128,0.18)")
    fig.update_yaxes(title_text="", autorange="reversed", gridcolor="rgba(0,0,0,0)")
    return fig


st.subheader("Rates by team, supervisor and site")
tabs = st.tabs(["Team", "Supervisor", "Site"])
for tab, (by, label) in zip(tabs, [("team", "Team"), ("supervisor", "Supervisor"), ("site", "Site")]):
    with tab:
        ui.show(rates_by(by, label))
st.caption(" · ".join(f"**{ui.RATE_LABELS[r]}**: {ui.RATE_DEFINITIONS[r]}" for r in rate_cols))

st.subheader("Ramp since enablement")
ramp = ui.q(metrics.ramp_curve, f, bucket_days=7, by="team")
overall = ui.q(metrics.ramp_curve, f, bucket_days=7)
if overall.empty:
    ui.no_data("tool-enabled calls in this selection")
else:
    min_calls = 20
    ramp = ramp[ramp["enabled_eligible_calls"] >= min_calls]
    fig = px.line(ramp, x="days_since_enabled", y="tool_adoption", color="team",
                  color_discrete_map=ui.team_colors(), custom_data=["enabled_eligible_calls", "agents"],
                  labels={"team": "Team"})
    fig.update_traces(line_width=2, opacity=0.75,
                      hovertemplate="%{y:.1%} (%{customdata[0]:,} calls, %{customdata[1]} agents)")
    fig.add_scatter(x=overall["days_since_enabled"], y=overall["tool_adoption"], name="All selected",
                    mode="lines", line=dict(color="#0b0b0b", width=3), hovertemplate="%{y:.1%}")
    fig = ui.style(fig, pct_axis=True)
    fig.update_xaxes(title="Days since the agent's tool was enabled (7-day buckets)")
    ui.show(fig)
    st.caption("Each agent is aligned on their own tool_enabled_date (day 0). "
               f"Team points with fewer than {min_calls} tool-enabled eligible calls are hidden.")

st.subheader("Agents")
min_enabled = st.slider("Minimum tool-enabled eligible calls per agent", 5, 100, 20, step=5,
                        help="Agents with fewer calls in the selection are left out of both lists.")
st.caption(f"Showing agents with at least **{min_enabled}** tool-enabled eligible calls in the selection.")
cols = {"agent_name": "Agent", "team": "Team", "enabled_eligible_calls": "Calls",
        "tool_adoption": "Adoption"}
config = {
    "Adoption": st.column_config.ProgressColumn("Adoption", format="%.0f%%", min_value=0,
                                                 max_value=100, width="small"),
    "Calls": st.column_config.NumberColumn(format="%d", width="small",
                                           help="Tool-enabled eligible calls in the selection"),
}


def agent_table(df):
    if df.empty:
        st.info("No agents meet the minimum call threshold. Lower it or widen the filters.")
        return
    out = df.head(10)[list(cols)].rename(columns=cols)
    out["Adoption"] = out["Adoption"] * 100
    st.dataframe(out, hide_index=True, use_container_width=True, column_config=config)


left, right = st.columns(2)
with left:
    st.markdown("**Top adopters**")
    agent_table(ui.q(metrics.agent_leaderboard, f, min_enabled_calls=min_enabled))
with right:
    st.markdown("**Low adopters** (coaching candidates)")
    agent_table(ui.q(metrics.low_adopters, f, min_enabled_calls=min_enabled))

ui.footnote()
