"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
The top menu and filter bar are drawn here once, so filters carry across every page.
"""

from pathlib import Path
import hashlib
import importlib
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Translation Tool Adoption", page_icon="🌐", layout="wide",
                   initial_sidebar_state="collapsed")

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))   # so pages can `import ui`


def code_version() -> str:
    """Hash of the shared modules, SQL views, config and data files."""
    files = [APP / "ui.py", ROOT / "src" / "metrics.py", ROOT / "config.py",
             *sorted((ROOT / "sql").glob("*.sql")), *sorted((ROOT / "data" / "raw").glob("*.parquet"))]
    h = hashlib.sha1()
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def load_ui():
    """Import ui (and src.metrics, config), reloading them when the code or data changed.
    A redeploy without a restart re-runs this script but can keep modules imported
    by the previous version, so they are reloaded here and ui.VERSION keys all caches."""
    version = code_version()
    import ui
    if getattr(ui, "VERSION", None) != version:   # older versions had no VERSION
        importlib.reload(ui.metrics.cfg)
        importlib.reload(ui.metrics)
        ui = importlib.reload(ui)
        ui.VERSION = version
    return ui


ui = load_ui()
metrics = ui.metrics


ELIGIBILITY_HELP = (
    "Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese calls handled by an agent who "
    "is not native in that language and whose translation tool was enabled on the call date. "
    "Adopted the tool: a translation session is linked to the call. "
    "Did not adopt: interpreter line or no support.")

NOT_ADOPTED_HELP = ("Tool-enabled eligible calls where the agent used the interpreter line or "
                    "no support instead of the translation tool.")

CARD_CSS = """
<style>
.st-key-adoption_card, .st-key-not_adopted_card {
  border: 1.5px solid #1F2937; border-radius: 0.75rem; padding: 1.25rem 1.5rem;
}
</style>
"""
CARD_HEIGHT = 340   # chart height in both Overview cards
OUTLINE = dict(color="#1F2937", width=1.5)
TREND_COLORS = {"interpreter_calls": "#F4A261", "no_support_calls": "#E76F51",
                "not_adopted_share": "#1D3557"}


def adoption_donut(split, share):
    """Two-slice donut with the adoption % in the center."""
    fig = go.Figure(go.Pie(
        labels=split["slice"], values=split["calls"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=[ui.PATH_COLORS["translation_tool"], ui.NOT_ADOPTED_COLOR],
                    line=OUTLINE),
        textinfo="none", customdata=split["share"],
        hovertemplate="%{label}<br>%{value:,} calls (%{customdata:.1%})<extra></extra>"))
    fig.add_annotation(text=f"<b>{share:.1%}</b>", x=0.5, y=0.55, showarrow=False,
                       font=dict(size=38, color="#0b0b0b"))
    fig.add_annotation(text="adoption", x=0.5, y=0.40, showarrow=False,
                       font=dict(size=14, color="#52514e"))
    fig.update_layout(height=CARD_HEIGHT, margin=dict(l=0, r=0, t=0, b=0), showlegend=True,
                      legend=dict(orientation="h", x=0, xanchor="left", y=-0.02, yanchor="top",
                                  font=dict(size=13)))
    return fig


def not_adopted_chart(trend, daily, start, end):
    """Stacked interpreter / no-support bars with % not using the tool on a second axis."""
    period = "%a %b %d, %Y" if daily else "Week of %b %d, %Y"
    fig = go.Figure()
    for col, name in (("interpreter_calls", "Interpreter line"), ("no_support_calls", "No support")):
        fig.add_bar(x=trend["period_start"], y=trend[col], name=name,
                    marker=dict(color=TREND_COLORS[col], line=dict(width=0)),
                    hovertemplate=f"{name}: %{{y:,}} calls<extra></extra>")
    fig.add_scatter(x=trend["period_start"], y=trend["not_adopted_share"], name="% not using the tool",
                    yaxis="y2", mode="lines+markers",
                    line=dict(color=TREND_COLORS["not_adopted_share"], width=2.5),
                    marker=dict(size=6 if daily else 7),
                    hovertemplate="% not using the tool: %{y:.1%}<extra></extra>")
    grid = "rgba(31,41,55,0.10)"
    fig.update_layout(
        barmode="stack", height=CARD_HEIGHT, hovermode="x unified", bargap=0.25,
        margin=dict(l=10, r=10, t=10, b=10), font=dict(size=13),
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.22, yanchor="top", title=None),
        xaxis=dict(title_text="Day" if daily else "Week starting", showgrid=False,
                   tickformat="%b %d", hoverformat=period,
                   range=[pd.Timestamp(start) - pd.Timedelta(hours=12),
                          pd.Timestamp(end) + pd.Timedelta(hours=12)] if daily else None),
        yaxis=dict(title_text="Calls without the tool", gridcolor=grid, zeroline=False,
                   rangemode="tozero"),
        yaxis2=dict(title_text="% not using the tool", overlaying="y", side="right",
                    tickformat=".0%", range=[0, 1.05], dtick=0.25, showgrid=False, zeroline=False))
    return fig


def overview():
    """Adoption donut card and calls-without-the-tool trend card, each with a CSV
    download for the active filters."""
    f = ui.page_header("Translation Tool Adoption")
    split = ui.q(metrics.adoption_split, f)
    total = int(split["calls"].sum())
    if total == 0:
        ui.no_data("tool-enabled eligible calls in this selection (the tool may not be "
                   "rolled out yet for these teams and dates)")
        st.stop()
    adopted = split.set_index("slice").loc["Adopted the tool"]

    st.html(CARD_CSS)
    left, right = st.columns([0.43, 0.57])   # stacked on a phone, left card first
    with left, st.container(key="adoption_card", height="stretch"):
        st.subheader("Adoption Percentage", anchor=False)
        ui.show(adoption_donut(split, adopted["share"]), width=320)   # compact, left-aligned
        st.markdown(f"**{int(adopted['calls']):,}** of **{total:,}** eligible calls adopted the tool",
                    help=ELIGIBILITY_HELP)
        csv = split.assign(start_date=f.start, end_date=f.end,
                           teams="; ".join(f.teams or ["all"]),
                           supervisors="; ".join(f.supervisors or ["all"]),
                           languages="; ".join(f.languages))
        st.download_button("Download CSV", csv.to_csv(index=False), "adoption_split.csv",
                           "text/csv", icon=":material/download:")

    with right, st.container(key="not_adopted_card", height="stretch"):
        st.subheader("Eligible Calls Without the Tool", anchor=False, help=NOT_ADOPTED_HELP)
        daily = metrics.not_adopted_grain(f.start, f.end) == "day"
        trend = ui.q(metrics.not_adopted_trend, f)
        ui.show(not_adopted_chart(trend, daily, f.start, f.end))
        not_adopted = int(trend["not_adopted_calls"].sum())
        st.markdown(f"**{not_adopted:,}** tool-enabled eligible calls did not use the tool "
                    f"({'daily' if daily else 'weekly'})")
        csv = pd.DataFrame({
            "period_start": trend["period_start"].dt.date,
            "eligible_calls": trend["eligible_calls"],
            "interpreter_calls": trend["interpreter_calls"],
            "no_support_calls": trend["no_support_calls"],
            "not_adopted_calls": trend["not_adopted_calls"],
            "pct_not_using_tool": trend["not_adopted_share"].round(4)})
        st.download_button("Download CSV", csv.to_csv(index=False),
                           f"calls_without_tool_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}.csv",
                           "text/csv", icon=":material/download:", key="not_adopted_csv")

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
