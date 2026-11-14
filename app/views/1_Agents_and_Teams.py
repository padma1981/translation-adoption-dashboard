"""Agents & Teams: adoption by language and high / low adopters for one team or supervisor.

Uses the Overview definition throughout: adoption = tool calls / (tool + interpreter calls)
among tool-enabled eligible calls; no-support calls are not counted in adoption (they are
in the coaching export). Filters: the shared date range plus Team and Supervisor dropdowns.
"""

from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
from ui import metrics

# The adopter cards size to their tables (both show up to 10 agents); the low adopters'
# column also holds the coaching downloads, so the row is not stretched to equal heights.
PAGE_CSS = ui.card_css(["card_lang", "card_high", "card_low"]) + f"""
<style>
.ag-selection {{ color: {ui.NAVY}; font-weight: 700; font-size: 1.05rem; margin: -0.5rem 0 0.25rem; }}
.ag-headline {{ color: {ui.NAVY}; font-weight: 700; font-size: 1.15rem; margin: 0 0 0.25rem; }}
.st-key-section_gap {{ height: 1.25rem; }}
</style>
"""
LOW_HELP = ("Calls without the tool are tool-enabled eligible calls handled with the interpreter "
            "line or no language support. No-support calls aren't counted in the adoption %, but "
            "they're included in the coaching export.")
LANG_HELP = ("Adoption = tool calls / (tool + interpreter calls) among tool-enabled eligible calls "
             "(no-support calls aren't counted). The navy line on each bar is the all-teams "
             "adoption for that language in the same dates.")
HIGH_HELP = "Top 10 agents by adoption % among those with enough eligible calls to rank."
TABLE_COLUMNS = {"agent_name": "Agent", "team": "Team", "eligible_calls": "Eligible calls",
                 "tool_calls": "Tool calls", "calls_without_tool": "Calls without the tool",
                 "tool_adoption": "Adoption"}

st.html(PAGE_CSS)
ui.title_row("Agents & Teams", centered=False)
selection_slot = st.empty()
f = ui.team_filters()
selection_slot.markdown(f"<p class='ag-selection'>{ui.selection_line(f)}</p>",
                        unsafe_allow_html=True)
supervisor_view = ui.role() == "supervisor"   # their data, all-teams figures included, is their team

split = ui.q(metrics.adoption_split, f, exclude_no_support=True)
if int(split["calls"].sum()) == 0:
    st.info("No tool-enabled eligible calls for this team, supervisor and dates. Try a wider "
            "date range or All teams.", icon="🔎")
    st.stop()
team_label = f.teams[0] if f.teams else "All teams"
file_tag = (f.teams[0] if f.teams else "all-teams") + f"_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}"


# --- D. Adoption by language --------------------------------------------------------------

def language_chart(df, show_all):
    """Horizontal adoption bars per language with bold % and call labels, and a thin navy
    marker for the all-teams adoption of that language."""
    labels = [("  No tool-enabled calls" if pd.isna(a) else f"  {a:.1%} · {int(c):,} calls")
              for a, c in zip(df["tool_adoption"], df["counted_calls"])]
    custom = df[["counted_calls", "enabled_tool_calls", "all_teams_adoption"]]
    fig = go.Figure(go.Bar(
        y=df["language"], x=df["tool_adoption"].fillna(0), orientation="h", customdata=custom,
        marker=dict(color=[ui.LANGUAGE_COLORS[l] for l in df["language"]], line=dict(width=0)),
        text=labels, textposition="outside", cliponaxis=False,
        textfont=dict(size=13, color=ui.NAVY),
        hovertemplate=("<b>%{y}</b><br>" + team_label + ": %{x:.1%} (%{customdata[1]:,} of "
                       "%{customdata[0]:,} calls)"
                       + ("<br>All teams: %{customdata[2]:.1%}" if show_all else "")
                       + "<extra></extra>")))
    if show_all:
        fig.add_scatter(
            y=df["language"], x=df["all_teams_adoption"], mode="markers", name="All teams",
            customdata=df[["tool_adoption"]],
            marker=dict(symbol="line-ns", size=34, line=dict(width=3, color=ui.NAVY)),
            hovertemplate=("<b>%{y}</b><br>All teams: %{x:.1%}<br>" + team_label
                           + ": %{customdata[0]:.1%}<extra></extra>"))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, height=90 * len(df) + 60, bargap=0.38, showlegend=False,
        hovermode="closest", dragmode=False, margin=dict(l=10, r=10, t=10, b=10),
        font=dict(size=12), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[0, 1.32], tickvals=[0, 0.25, 0.5, 0.75, 1], tickformat=".0%",
                   gridcolor=ui.GRID, zeroline=False, fixedrange=True),
        yaxis=dict(autorange="reversed", showgrid=False, fixedrange=True, tickfont=dict(size=14)))
    return fig


sel = ui.q(metrics.overview_adoption, f, by="language")
everyone = ui.q(metrics.overview_adoption, replace(f, teams=None, supervisors=None), by="language")
langs = sel.merge(everyone[["language", "tool_adoption"]].rename(
    columns={"tool_adoption": "all_teams_adoption"}), on="language", how="left")
counted, tool = int(langs["counted_calls"].sum()), int(langs["enabled_tool_calls"].sum())

st.subheader("Adoption by Language", anchor=False, help=LANG_HELP)
with st.container(key="card_lang"):
    st.markdown(f"<p class='ag-headline'>{team_label}: {tool / counted:.1%} adoption on "
                f"{counted:,} eligible calls</p>", unsafe_allow_html=True)
    ui.show(language_chart(langs, show_all=not supervisor_view))
    st.caption("Navy line: all-teams adoption for that language." if not supervisor_view
               else "Your data is limited to your team, so the all-teams line isn't shown.")
csv = pd.DataFrame({
    "language": langs["language"], "eligible_calls": langs["counted_calls"],
    "tool_calls": langs["enabled_tool_calls"], "interpreter_calls": langs["enabled_interpreter_calls"],
    "adoption_pct": (langs["tool_adoption"] * 100).round(1),
    "all_teams_adoption_pct": (langs["all_teams_adoption"] * 100).round(1)})
st.download_button("Download CSV", ui.with_selection(csv, f).to_csv(index=False),
                   f"adoption_by_language_{file_tag}.csv", "text/csv",
                   icon=":material/download:", key="lang_csv")

with st.container(key="section_gap"):
    pass


# --- E. High and low adopters ----------------------------------------------------------------

def adopter_table(df, color):
    """Agent table: bold names, counts, adoption as a progress bar in the card's color."""
    shown = df[list(TABLE_COLUMNS)].rename(columns=TABLE_COLUMNS)
    shown["Adoption"] = shown["Adoption"] * 100
    styled = (shown.style.set_properties(subset=["Agent"], **{"font-weight": "700"})
              .format({"Adoption": "{:.1f}%"}))
    # Fixed widths keep the six columns inside a half-width card with room for the % label.
    config = {
        "Agent": st.column_config.Column(width=138),
        "Team": st.column_config.Column(width=70),
        "Eligible calls": st.column_config.NumberColumn("Eligible", format="localized", width=62,
                                                        help="Eligible calls (tool + interpreter line)"),
        "Tool calls": st.column_config.NumberColumn("Tool", format="localized", width=52,
                                                    help="Tool calls"),
        "Calls without the tool": st.column_config.NumberColumn(
            "Without tool", format="localized", width=84,
            help="Calls without the tool: interpreter line or no support"),
        "Adoption": st.column_config.ProgressColumn(
            "Adoption", min_value=0, max_value=100, format="%.1f%%", color=color, width=150),
    }
    st.dataframe(styled, hide_index=True, width="stretch", column_config=config)


st.subheader("Agents: High and Low Adopters", anchor=False)
n = st.slider("Minimum eligible calls to rank an agent", 5, 50, 20, key="ag_min_calls", width=320)
st.caption(f"Agents with fewer than {n} eligible calls aren't ranked.")
high = ui.q(metrics.adopter_ranking, f, min_calls=n)
low = ui.q(metrics.adopter_ranking, f, min_calls=n, low=True)

with st.container(key="row_adopters"):
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### High Adopters", help=HIGH_HELP)
        with st.container(key="card_high"):
            if high.empty:
                st.info(f"No agents have {n} or more eligible calls here.")
            else:
                adopter_table(high, ui.TEAL)
    with right:
        st.markdown("#### Low Adopters", help=LOW_HELP)
        with st.container(key="card_low"):
            if low.empty:
                st.info(f"No agents have {n} or more eligible calls here.")
            else:
                adopter_table(low, ui.ORANGE)
        if not low.empty:
            calls = ui.q(metrics.coaching_calls, f, agent_ids=tuple(low["agent_id"]))
            st.download_button("Download calls for coaching (CSV)", calls.to_csv(index=False),
                               f"coaching_calls_{file_tag}.csv", "text/csv",
                               icon=":material/download:", key="coaching_csv",
                               help="Every tool-enabled eligible call where the tool wasn't "
                                    "used (interpreter line or no support), for the low "
                                    "adopters shown.")
            names = dict(zip(low["agent_id"], low["agent_name"]))
            agent = st.selectbox("One agent's calls", list(names), format_func=names.get,
                                 key="ag_coach_agent")
            one = calls[calls["agent_id"] == agent]
            slug = names[agent].replace(" ", "-")
            st.download_button(f"Download {names[agent]}'s calls (CSV)", one.to_csv(index=False),
                               f"coaching_calls_{slug}_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}.csv",
                               "text/csv", icon=":material/download:", key="coaching_one_csv")

ui.footnote()
