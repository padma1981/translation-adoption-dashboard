"""Cost: interpreter minutes and spend, spend where the tool was available, cost avoided."""

import plotly.express as px
import streamlit as st

import ui
from ui import metrics

f = ui.page_header("Cost")
k = ui.q(metrics.kpi_summary, f).iloc[0]
rate = metrics.cfg.INTERPRETER_COST_PER_MIN

cols = st.columns(4)
cols[0].metric("Interpreter minutes", ui.num(k["interpreter_minutes"]), border=True)
cols[1].metric("Interpreter spend", ui.money(k["interpreter_spend_usd"]), border=True)
cols[2].metric("Spend, tool available", ui.money(k["interpreter_spend_where_tool_available_usd"]),
               border=True, help="Interpreter spend on calls where the agent already had the tool.")
cols[3].metric("Estimated cost avoided", ui.money(k["cost_avoided_usd"]), border=True)
st.caption(f"Interpreter line billed at ${rate:.2f}/minute. \"Tool was available\" = the agent's "
           "translation tool was already enabled on the call date, so the interpreter was a missed "
           "chance to use the tool.")

st.subheader("Interpreter minutes and spend")
spend = ui.q(metrics.interpreter_spend, f, grain="week")
spend["Tool status"] = spend["tool_available"].map({False: "Tool not yet enabled",
                                                    True: "Tool was available"})
measure = st.radio("Show", ["interpreter_spend_usd", "interpreter_minutes"], horizontal=True,
                   format_func={"interpreter_spend_usd": "Spend ($)",
                                "interpreter_minutes": "Minutes"}.get)
fig = px.bar(spend, x="week_start", y=measure, color="Tool status", pattern_shape="Tool status",
             color_discrete_map={"Tool not yet enabled": ui.PATH_COLORS["interpreter_line"],
                                 "Tool was available": ui.PATH_COLORS["interpreter_line"]},
             pattern_shape_map={"Tool not yet enabled": "", "Tool was available": "/"},
             category_orders={"Tool status": ["Tool not yet enabled", "Tool was available"]},
             custom_data=["interpreter_calls"])
fig.update_traces(hovertemplate=("$%{y:,.0f}" if measure == "interpreter_spend_usd" else "%{y:,} min")
                  + " · %{customdata[0]:,} calls", marker_line=dict(color="white", width=1))
fig = ui.style(fig)
fig.update_yaxes(tickprefix="$" if measure == "interpreter_spend_usd" else "", tickformat=",")
ui.show(fig)
st.caption("Weekly interpreter use. The hatched part is interpreter use by agents who already had "
           "the tool; it should shrink as adoption grows.")

st.subheader("Estimated interpreter cost avoided")
left, right = st.columns([3, 2])
with left:
    avoided = ui.q(metrics.cost_avoided, f, grain="week")
    if avoided.empty:
        ui.no_data("tool-supported calls in this selection")
    else:
        fig = px.bar(avoided, x="week_start", y="cost_avoided_usd", custom_data=["tool_calls"])
        fig.update_traces(marker_color=ui.PATH_COLORS["translation_tool"],
                          hovertemplate="$%{y:,.0f} · %{customdata[0]:,} tool calls")
        fig = ui.style(fig, legend=False)
        fig.update_yaxes(tickprefix="$", tickformat=",", title_text="")
        ui.show(fig)
        st.caption("By week.")
with right:
    by_lang = ui.q(metrics.cost_avoided_by_language, f)
    if not by_lang.empty:
        fig = px.bar(by_lang, x="cost_avoided_usd", y="language", orientation="h", color="language",
                     color_discrete_map=ui.LANGUAGE_COLORS, text_auto="$,.0f",
                     category_orders={"language": list(f.languages)})
        fig.update_traces(hovertemplate="%{y}: $%{x:,.0f}", textposition="outside", cliponaxis=False)
        fig = ui.style(fig, legend=False)
        fig.update_layout(hovermode="closest")
        fig.update_xaxes(tickprefix="$", range=[0, by_lang["cost_avoided_usd"].max() * 1.3])
        fig.update_yaxes(title_text="", gridcolor="rgba(0,0,0,0)")
        ui.show(fig)
        st.caption("By language, whole selected period.")

st.caption(
    f"**How it's estimated:** for each language, cost avoided = tool-supported eligible calls × the "
    f"share of eligible calls that used an interpreter before rollout × average interpreter minutes "
    f"per interpreter call before rollout × ${rate:.2f}/min. \"Before rollout\" means calls before the "
    f"first team rollout ({ui.options()['first_rollout_date']:%b %d, %Y}); that baseline is fixed and "
    f"does not change with the filters. Native-speaker optional use and unlinked practice sessions are "
    f"not counted.")

if not by_lang.empty:
    with st.expander("Baseline per language"):
        t = by_lang[["language", "tool_calls", "interpreter_share", "avg_interpreter_minutes",
                     "avoided_usd_per_tool_call", "cost_avoided_usd"]].copy()
        t["interpreter_share"] = t["interpreter_share"].map(ui.pct)
        t["avg_interpreter_minutes"] = t["avg_interpreter_minutes"].round(1)
        t["avoided_usd_per_tool_call"] = t["avoided_usd_per_tool_call"].map(lambda x: f"${x:,.2f}")
        t["cost_avoided_usd"] = t["cost_avoided_usd"].map(ui.money)
        st.dataframe(t.rename(columns={
            "language": "Language", "tool_calls": "Tool calls", "interpreter_share": "Pre-rollout interp. share",
            "avg_interpreter_minutes": "Avg interp. min", "avoided_usd_per_tool_call": "$ per tool call",
            "cost_avoided_usd": "Cost avoided"}), hide_index=True, use_container_width=True)

ui.footnote()
