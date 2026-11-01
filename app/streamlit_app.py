"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
The top menu and filter bar are drawn here once, so filters carry across every page.
"""

from pathlib import Path
import hashlib
import importlib
import sys

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

REPEAT_HELP = ("Agents whose tool was enabled but who handled eligible calls with the interpreter line "
               "or no support instead of the translation tool, in the selected period and filters.")

SECTION_CSS = """
<style>
/* Only the charts get a border; headings, summaries and buttons sit on the page. */
.st-key-adoption_section [data-testid="stPlotlyChart"],
.st-key-repeat_section [data-testid="stPlotlyChart"] {
  border: 1px solid #CBD5E1; border-radius: 10px; padding: 6px; box-sizing: border-box;
}
</style>
"""
DONUT_HEIGHT = 280
MAX_AGENT_HEIGHT = 380
TOP_AGENTS = 15
MISSED_COLORS = {"interpreter_calls": "#F4A261", "no_support_calls": "#E76F51"}


def adoption_donut(split, share):
    """Two-slice donut with the adoption % in the center."""
    fig = go.Figure(go.Pie(
        labels=split["slice"], values=split["calls"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=[ui.PATH_COLORS["translation_tool"], ui.NOT_ADOPTED_COLOR],
                    line=dict(color="white", width=2)),
        textinfo="none", customdata=split["share"],
        hovertemplate="%{label}<br>%{value:,} calls (%{customdata:.1%})<extra></extra>"))
    fig.add_annotation(text=f"<b>{share:.1%}</b>", x=0.5, y=0.55, showarrow=False,
                       font=dict(size=32, color="#0b0b0b"))
    fig.add_annotation(text="adoption", x=0.5, y=0.40, showarrow=False,
                       font=dict(size=13, color="#52514e"))
    fig.update_layout(height=DONUT_HEIGHT, margin=dict(l=0, r=0, t=0, b=0), showlegend=True,
                      legend=dict(orientation="h", x=0, xanchor="left", y=-0.02, yanchor="top",
                                  font=dict(size=13)))
    return fig


def repeat_non_users_chart(agents):
    """Horizontal stacked bars of missed calls per agent, most missed at the top,
    with each agent's adoption % at the end of the bar."""
    labels = agents["agent_name"] + " (" + agents["team"] + ")"
    custom = agents[["agent_name", "team", "supervisor", "interpreter_calls", "no_support_calls",
                     "missed_calls", "enabled_eligible_calls", "tool_adoption"]]
    hover = ("<b>%{customdata[0]}</b><br>Team: %{customdata[1]}<br>Supervisor: %{customdata[2]}<br>"
             "Missed calls: %{customdata[5]:,} (interpreter %{customdata[3]:,}, "
             "no support %{customdata[4]:,})<br>Tool-enabled eligible calls: %{customdata[6]:,}<br>"
             "Adoption: %{customdata[7]:.1%}<extra></extra>")
    fig = go.Figure()
    for col, name in (("interpreter_calls", "Interpreter line"), ("no_support_calls", "No support")):
        fig.add_bar(y=labels, x=agents[col], name=name, orientation="h", customdata=custom,
                    marker=dict(color=MISSED_COLORS[col], line=dict(width=0)), hovertemplate=hover)
    fig.add_scatter(y=labels, x=agents["missed_calls"], mode="text", showlegend=False,
                    text=[f" {a:.0%} adoption" for a in agents["tool_adoption"]],
                    textposition="middle right", textfont=dict(size=11, color="#52514e"),
                    hoverinfo="skip")
    height = max(DONUT_HEIGHT, min(MAX_AGENT_HEIGHT, 14 * len(agents) + 120))
    fig.update_layout(
        barmode="stack", height=height, bargap=0.3, hovermode="closest",
        margin=dict(l=10, r=10, t=10, b=10), font=dict(size=12),
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.2, yanchor="top", title=None,
                    traceorder="normal"),
        xaxis=dict(title_text="Missed calls", gridcolor="rgba(31,41,55,0.10)", zeroline=False,
                   range=[0, agents["missed_calls"].max() * 1.35]),
        yaxis=dict(autorange="reversed", showgrid=False, automargin=True))
    return fig


def overview():
    """Adoption donut and agents repeatedly not using the tool, each with a CSV
    download for the active filters."""
    f = ui.page_header("Translation Tool Adoption")
    split = ui.q(metrics.adoption_split, f)
    total = int(split["calls"].sum())
    if total == 0:
        ui.no_data("tool-enabled eligible calls in this selection (the tool may not be "
                   "rolled out yet for these teams and dates)")
        st.stop()
    adopted = split.set_index("slice").loc["Adopted the tool"]

    st.html(SECTION_CSS)
    left, right = st.columns([0.4, 0.6], gap="large")   # stacked on a phone, left first
    with left, st.container(key="adoption_section"):
        st.subheader("Adoption Percentage", anchor=False)
        ui.show(adoption_donut(split, adopted["share"]), width=300)   # compact, left-aligned
        st.markdown(f"**{int(adopted['calls']):,}** of **{total:,}** eligible calls adopted the tool",
                    help=ELIGIBILITY_HELP)
        csv = split.assign(start_date=f.start, end_date=f.end,
                           teams="; ".join(f.teams or ["all"]),
                           supervisors="; ".join(f.supervisors or ["all"]),
                           languages="; ".join(f.languages))
        st.download_button("Download CSV", csv.to_csv(index=False), "adoption_split.csv",
                           "text/csv", icon=":material/download:")

    with right, st.container(key="repeat_section"):
        st.subheader("Agents Repeatedly Not Using the Tool", anchor=False, help=REPEAT_HELP)
        min_missed = st.columns([0.4, 0.6])[0].number_input(
            "Minimum missed calls", min_value=1, value=3, step=1, key="min_missed")
        agents = ui.q(metrics.repeat_non_users, f, min_missed=int(min_missed))
        if agents.empty:
            st.info(f"No agents have {min_missed} or more missed calls for these filters.", icon="🎉")
        else:
            ui.show(repeat_non_users_chart(agents.head(TOP_AGENTS)))
            st.markdown(f"**{len(agents):,}** agents with **{int(agents['missed_calls'].sum()):,}** "
                        f"missed calls (at least {min_missed} each)")
            if len(agents) > TOP_AGENTS:
                st.caption(f"Showing {TOP_AGENTS} of {len(agents):,} agents; the CSV includes all.")
            calls = ui.q(metrics.missed_call_details, f, min_missed=int(min_missed))
            st.download_button("Download CSV", calls.to_csv(index=False),
                               f"missed_calls_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}.csv",
                               "text/csv", icon=":material/download:", key="missed_calls_csv")

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
