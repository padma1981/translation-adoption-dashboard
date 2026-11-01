"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
The top menu and filter bar are drawn here once, so filters carry across every page.
"""

from pathlib import Path
import sys

import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Translation Tool Adoption", page_icon="🌐", layout="wide",
                   initial_sidebar_state="collapsed")

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so pages can `import ui`
import ui  # noqa: E402
from ui import metrics  # noqa: E402


def overview():
    """Headline rates, volume and cost, and how they move over time."""
    f = ui.page_header("Translation Tool Adoption",
                       "Contact center calls in Spanish, Portuguese, Mandarin and Vietnamese.")
    k = ui.q(metrics.kpi_summary, f).iloc[0]

    cols = st.columns(3)
    for col, rate in zip(cols, ui.RATE_LABELS):
        col.metric(ui.RATE_LABELS[rate], ui.pct(k[rate]), border=True)
        col.caption(ui.RATE_DEFINITIONS[rate])
        if k[rate] != k[rate]:   # NaN: no calls in the denominator
            col.caption("No calls in this selection to measure this rate.")

    cols = st.columns(3)
    cols[0].metric("Eligible calls", ui.num(k["eligible_calls"]), border=True)
    cols[0].caption("In-scope language calls handled by a non-native agent.")
    cols[1].metric("Interpreter spend", ui.money(k["interpreter_spend_usd"]), border=True)
    cols[1].caption(f"{ui.num(k['interpreter_minutes'])} interpreter minutes.")
    cols[2].metric("Estimated cost avoided", ui.money(k["cost_avoided_usd"]), border=True)
    cols[2].caption("Interpreter cost the tool-supported calls would likely have needed. See Cost.")

    st.subheader("Weekly rates")
    trend = ui.q(metrics.adoption_trend, f, grain="week")
    fig = ui.rate_lines(trend, "week_start")
    ui.mark_dates(fig, ui.q(metrics.team_rollout_dates, f), "team", "rollout_date", f.start, f.end)
    ui.show(ui.style(fig, pct_axis=True))
    st.caption("Dotted lines mark each selected team's tool rollout. Weeks start on Monday; "
               "partial weeks at either end of the range have fewer calls.")

    st.subheader("Handling path mix")
    mix = ui.path_label(ui.q(metrics.handling_path_trend, f, grain="week"))
    left, right = st.columns([2, 1])
    with left:
        fig = px.bar(mix, x="week_start", y="share_of_period", color="Handling path",
                     color_discrete_map={ui.PATH_LABELS[p]: c for p, c in ui.PATH_COLORS.items()},
                     category_orders={"Handling path": [ui.PATH_LABELS[p] for p in ui.PATH_ORDER]},
                     custom_data=["calls"])
        fig.update_traces(hovertemplate="%{y:.1%} (%{customdata[0]:,} calls)", marker_line_width=0)
        fig.update_layout(bargap=0.15)
        ui.show(ui.style(fig, pct_axis=True))
        st.caption("Share of eligible calls each week by how they were handled.")
    with right:
        totals = (mix.groupby(["handling_path", "Handling path"], as_index=False)["calls"].sum()
                  .sort_values("handling_path", key=lambda s: s.map(ui.PATH_ORDER.index)))
        fig = px.pie(totals, names="Handling path", values="calls", hole=0.55,
                     color="Handling path",
                     color_discrete_map={ui.PATH_LABELS[p]: c for p, c in ui.PATH_COLORS.items()})
        fig.update_traces(textinfo="percent", hovertemplate="%{label}: %{value:,} calls",
                          sort=False, marker_line=dict(color="white", width=2))
        ui.show(ui.style(fig, legend=True).update_layout(hovermode=False))
        st.caption("Whole selected period.")

    ui.footnote()


pages = [
    st.Page(overview, title="Overview", icon="📊", default=True),
    st.Page("views/1_Agents_and_Teams.py", title="Agents & Teams", icon="👥"),
    st.Page("views/2_Languages.py", title="Languages", icon="🗣️"),
    st.Page("views/3_Operational_Impact.py", title="Operational Impact", icon="⏱️"),
    st.Page("views/4_Cost.py", title="Cost", icon="💵"),
    st.Page("views/5_Data_Quality.py", title="Data Quality", icon="🧪"),
]
page = st.navigation(pages, position="top")
ui.render_filter_bar()
page.run()
