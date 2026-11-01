"""Operational Impact: handle time, hold, transfers and CSAT by handling path."""

import plotly.express as px
import streamlit as st

import ui
from ui import metrics

f = ui.page_header("Operational Impact",
                   "Native-speaker calls (not eligible) are shown in gray as a baseline.")

MEASURES = {
    "avg_handle_sec": ("Avg handle time (min)", 1 / 60, ".1f"),
    "avg_hold_sec": ("Avg hold time (sec)", 1, ".0f"),
    "transfer_rate": ("Transfer rate", 1, ".1%"),
    "avg_csat": ("Avg CSAT (1-5)", 1, ".2f"),
}
segments = ui.PATH_ORDER
color_map = {ui.PATH_LABELS[p]: c for p, c in ui.PATH_COLORS.items()}
label_order = [ui.PATH_LABELS[p] for p in segments]

overall = ui.path_label(ui.q(metrics.operational_by_path, f), "segment")
overall = overall[overall["segment"].isin(segments)]

st.subheader("Overall by handling path")
grid = st.columns(2) + st.columns(2)   # two rows of two
for col, (measure, (label, scale, fmt)) in zip(grid, MEASURES.items()):
    d = overall.assign(value=overall[measure] * scale)
    fig = px.bar(d, x="value", y="Handling path", color="Handling path", orientation="h",
                 color_discrete_map=color_map, category_orders={"Handling path": label_order},
                 text_auto=fmt, custom_data=["calls", "csat_responses"])
    hover = "%{x:" + fmt + "} · %{customdata[0]:,} calls"
    if measure == "avg_csat":
        hover = "%{x:.2f} · %{customdata[1]:,} survey responses"
        fig.update_xaxes(range=[1, 5.4])
    else:
        fig.update_xaxes(range=[0, d["value"].max() * 1.2])   # room for the outside labels
    fig.update_traces(hovertemplate=hover, textposition="outside", cliponaxis=False)
    fig = ui.style(fig, height=250, legend=False)
    fig.update_layout(title=dict(text=label, font=dict(size=14)), hovermode="closest")
    fig.update_yaxes(title_text="", gridcolor="rgba(0,0,0,0)")
    if fmt.endswith("%"):
        fig.update_xaxes(tickformat=".0%")
    with col:
        ui.show(fig)

st.caption("Handle time = talk + hold + after-call work. CSAT averages only calls with a survey response.")

st.subheader("By language")
by_lang = ui.path_label(ui.q(metrics.operational_by_path, f, by_language=True), "segment")
by_lang = by_lang[by_lang["segment"].isin(segments)]
choice = st.radio("Measure", list(MEASURES), format_func=lambda m: MEASURES[m][0], horizontal=True)
label, scale, fmt = MEASURES[choice]
d = by_lang.assign(value=by_lang[choice] * scale)
fig = px.bar(d, x="language", y="value", color="Handling path", barmode="group",
             color_discrete_map=color_map,
             category_orders={"Handling path": label_order, "language": list(f.languages)},
             custom_data=["calls"])
fig.update_traces(hovertemplate="%{y:" + fmt + "} · %{customdata[0]:,} calls")
fig = ui.style(fig, height=380, pct_axis=fmt.endswith("%"))
fig.update_yaxes(title=label)
if choice == "avg_csat":
    fig.update_yaxes(range=[1, 5])
ui.show(fig)

with st.expander("Table view"):
    t = by_lang[["language", "Handling path", "calls", "avg_handle_sec", "avg_hold_sec",
                 "transfer_rate", "avg_csat"]].copy()
    t["avg_handle_sec"] = (t["avg_handle_sec"] / 60).round(1)
    t["avg_hold_sec"] = t["avg_hold_sec"].round(0)
    t["transfer_rate"] = t["transfer_rate"].map(ui.pct)
    t["avg_csat"] = t["avg_csat"].round(2)
    st.dataframe(t.rename(columns={"language": "Language", "calls": "Calls",
                                   "avg_handle_sec": "Handle (min)", "avg_hold_sec": "Hold (sec)",
                                   "transfer_rate": "Transfers", "avg_csat": "CSAT"}),
                 hide_index=True, width="stretch")

ui.footnote()
