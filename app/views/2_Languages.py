"""Languages: eligible volume and adoption by language; native vs overflow routing."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui
from ui import metrics

f = ui.page_header("Languages")
langs = ui.q(metrics.language_summary, f)
order = [l for l in f.languages if l in set(langs["language"])]
langs = langs.set_index("language").loc[order].reset_index()

st.subheader("Eligible volume and tool adoption")
left, right = st.columns(2)
with left:
    fig = px.bar(langs, x="language", y="eligible_calls", color="language",
                 color_discrete_map=ui.LANGUAGE_COLORS, category_orders={"language": order},
                 text_auto=",.0f")
    fig.update_traces(hovertemplate="%{x}: %{y:,} eligible calls", textposition="outside",
                      cliponaxis=False)
    ui.show(ui.style(fig, height=340, legend=False))
    st.caption("Eligible calls: in-scope language calls handled by a non-native agent.")
with right:
    fig = px.bar(langs, x="language", y="tool_adoption", color="language",
                 color_discrete_map=ui.LANGUAGE_COLORS, category_orders={"language": order},
                 text_auto=".0%", custom_data=["enabled_eligible_calls"])
    fig.update_traces(hovertemplate="%{x}: %{y:.1%} of %{customdata[0]:,} tool-enabled calls",
                      textposition="outside", cliponaxis=False)
    ui.show(ui.style(fig, height=340, pct_axis=True, legend=False))
    st.caption(f"Tool adoption: {ui.RATE_DEFINITIONS['tool_adoption']}")

table = langs[["language", "in_scope_calls", "eligible_calls", "native_share", "overflow_rate",
               "tool_adoption", "interpreter_compliance", "supported_rate"]].copy()
for c in ["native_share", "overflow_rate", "tool_adoption", "interpreter_compliance", "supported_rate"]:
    table[c] = table[c].map(ui.pct)
st.dataframe(table.rename(columns={
    "language": "Language", "in_scope_calls": "Calls", "eligible_calls": "Eligible",
    "native_share": "Native share", "overflow_rate": "Overflow", "tool_adoption": "Adoption",
    "interpreter_compliance": "Interp. compliance", "supported_rate": "Supported"}),
    hide_index=True, width="stretch")

st.subheader("Routing: native agent vs overflow")
st.caption("In-scope calls go to a native speaker when one is free; the rest overflow to a "
           "non-native agent, which creates an eligible call.")
left, right = st.columns(2)
with left:
    routed = langs.melt(id_vars="language", value_vars=["native_routed_calls", "overflow_calls"],
                        var_name="route", value_name="calls")
    routed["Route"] = routed["route"].map({"native_routed_calls": "Native agent",
                                           "overflow_calls": "Overflow to non-native"})
    fig = px.bar(routed, x="language", y="calls", color="Route", barmode="stack",
                 color_discrete_map=ui.ROUTING_COLORS, category_orders={"language": order})
    fig.update_traces(hovertemplate="%{y:,} calls", marker_line=dict(color="white", width=1))
    ui.show(ui.style(fig, height=360))
    st.caption("In-scope calls by routing outcome, whole selected period.")
with right:
    weekly = ui.q(metrics.routing_mix, f, grain="week")
    fig = go.Figure()
    for lang in order:
        d = weekly[weekly["language"] == lang]
        fig.add_scatter(x=d["week_start"], y=d["native_share"], name=lang, mode="lines",
                        line=dict(color=ui.LANGUAGE_COLORS[lang], width=2),
                        customdata=d[["in_scope_calls"]], hovertemplate="%{y:.0%} of %{customdata[0]:,}")
    ui.show(ui.style(fig, height=360, pct_axis=True))
    st.caption("Native share by week: share of in-scope calls handled by a native speaker.")

ui.footnote()
