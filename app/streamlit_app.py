"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
Nothing but the sign-in screens is shown until a user is signed in (see auth.py).
The top menu (only the pages the user's role allows) and the filter bar are drawn
here once, so filters carry across every page.
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
    files = [APP / "ui.py", APP / "auth.py", ROOT / "src" / "metrics.py", ROOT / "src" / "users.py",
             ROOT / "config.py",
             *sorted((ROOT / "sql").glob("*.sql")), *sorted((ROOT / "data" / "raw").glob("*.parquet"))]
    h = hashlib.sha1()
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def load_ui():
    """Import ui and auth (and src.metrics, src.users, config), reloading them when the
    code or data changed.
    A redeploy without a restart re-runs this script but can keep modules imported
    by the previous version, so they are reloaded here and ui.VERSION keys all caches."""
    version = code_version()
    import ui
    import auth
    if getattr(ui, "VERSION", None) != version:   # older versions had no VERSION
        importlib.reload(ui.metrics.cfg)
        importlib.reload(ui.metrics)
        importlib.reload(auth.users)
        ui = importlib.reload(ui)
        auth = importlib.reload(auth)
        ui.VERSION = version
    return ui, auth


ui, auth = load_ui()
metrics = ui.metrics
users = auth.users


ELIGIBILITY_HELP = (
    "Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese calls handled by an agent who "
    "is not native in that language and whose translation tool was enabled on the call date. "
    "Adopted the tool: a translation session is linked to the call. "
    "Did not adopt: interpreter line or no support.")

REPEAT_HELP = ("Agents whose tool was enabled but who handled eligible calls with the interpreter line "
               "or no support instead of the translation tool, in the selected period and filters.")

SECTION_CSS = """
<style>
/* Cards: the donut's element container, and the Trends slider + chart container.
   Both sit directly under their headings, so the card tops line up. */
.st-key-adoption_section [data-testid="stElementContainer"]:has([data-testid="stPlotlyChart"]),
.st-key-trends_card {
  background: #FFFFFF;
  border: 1px solid #94A3B8; border-radius: 14px;
  padding: 12px 12px 6px; box-sizing: border-box;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.18), 0 2px 6px rgba(15, 23, 42, 0.10);
  overflow: visible; margin-bottom: 14px;
}
</style>
"""
DONUT_HEIGHT = 280
MAX_AGENT_HEIGHT = 380
TOP_AGENTS = 10
MISSED_COLOR = "#F4A261"
ADOPTED_COLOR = "#0F9D8A"      # teal
NOT_ADOPTED_COLOR = "#F4A261"  # soft orange
DEFAULT_MIN_MISSED = 3


def adoption_donut(split, share):
    """Two-slice donut with the adoption % in the center."""
    fig = go.Figure(go.Pie(
        labels=split["slice"], values=split["calls"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=[ADOPTED_COLOR, NOT_ADOPTED_COLOR],
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
    """Horizontal bars of total missed calls per agent, most missed at the top,
    with the count at the end of each bar."""
    labels = agents["agent_name"] + " (" + agents["team"] + ")"
    custom = agents[["agent_name", "team", "supervisor", "missed_calls", "enabled_eligible_calls",
                     "tool_adoption"]]
    fig = go.Figure(go.Bar(
        y=labels, x=agents["missed_calls"], orientation="h", customdata=custom,
        marker=dict(color=MISSED_COLOR, line=dict(width=0)),
        text=agents["missed_calls"], texttemplate="%{text:,}", textposition="outside",
        textfont=dict(size=11, color="#52514e"), cliponaxis=False,
        hovertemplate=("<b>%{customdata[0]}</b><br>Team: %{customdata[1]}<br>"
                       "Supervisor: %{customdata[2]}<br>Missed calls: %{customdata[3]:,}<br>"
                       "Tool-enabled eligible calls: %{customdata[4]:,}<br>"
                       "Adoption: %{customdata[5]:.1%}<extra></extra>")))
    height = max(DONUT_HEIGHT, min(MAX_AGENT_HEIGHT, 14 * len(agents) + 120))
    fig.update_layout(
        height=height, bargap=0.3, hovermode="closest", showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10), font=dict(size=12),
        xaxis=dict(title_text="Missed calls", gridcolor="rgba(31,41,55,0.10)", zeroline=False,
                   range=[0, agents["missed_calls"].max() * 1.15]),
        yaxis=dict(autorange="reversed", showgrid=False, automargin=True))
    return fig


def min_missed_slider(max_missed):
    """Slider for the minimum missed calls, kept within 1..max_missed as filters change."""
    if max_missed <= 1:   # a slider needs min < max
        return 1
    current = st.session_state.get("min_missed", DEFAULT_MIN_MISSED)
    st.session_state.min_missed = min(max(int(current), 1), max_missed)
    return st.slider("Minimum missed calls", min_value=1, max_value=max_missed, step=1,
                     key="min_missed")


def overview():
    """Adoption donut and agents repeatedly not using the tool, each with a CSV
    download for the active filters. Viewers see only the donut and its CSV."""
    f = ui.page_header("Translation Tool Adoption", centered=True, show_filters=False)
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

    if ui.role() == "viewer":   # no agent names or call-level exports for viewers
        ui.footnote()
        return
    with right, st.container(key="repeat_section"):
        all_missed = ui.q(metrics.repeat_non_users, f, min_missed=1)
        st.subheader("Trends", anchor=False, help=REPEAT_HELP)
        if all_missed.empty:
            st.info("No tool-enabled agent missed the tool for these filters.", icon="🎉")
        else:
            with st.container(key="trends_card"):
                min_missed = min_missed_slider(int(all_missed["missed_calls"].max()))
                agents = all_missed[all_missed["missed_calls"] >= min_missed].reset_index(drop=True)
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


# key: (page source, title, icon, url path). Keys match auth.PAGE_ACCESS.
PAGE_SPECS = {
    "overview": (overview, "Overview", "📊", "overview"),
    "agents": ("views/1_Agents_and_Teams.py", "Agents & Teams", "👥", "Agents_and_Teams"),
    "languages": ("views/2_Languages.py", "Languages", "🗣️", "Languages"),
    "operational": ("views/3_Operational_Impact.py", "Operational Impact", "⏱️", "Operational_Impact"),
    "cost": ("views/4_Cost.py", "Cost", "💵", "Cost"),
    "data_quality": ("views/5_Data_Quality.py", "Data Quality", "🧪", "Data_Quality"),
    "user_management": ("views/6_User_management.py", "User management", "🔐", "User_management"),
}


def pending_count():
    try:
        return len(users.list_users("pending"))
    except Exception:   # store unavailable: show the page without a count
        return 0


def make_pages(visible, with_default=True, titles=None):
    """All pages; those not in `visible` are registered hidden (not in the menu),
    so their URL still resolves and can show the no-access message."""
    titles = titles or {}
    return {key: st.Page(src, title=titles.get(key, title), icon=icon, url_path=path,
                         default=with_default and key == "overview",
                         visibility="visible" if key in visible else "hidden")
            for key, (src, title, icon, path) in PAGE_SPECS.items()}


user = auth.gate(make_pages)
allowed = auth.allowed_pages(user)
titles = {}
if "user_management" in allowed and (n := pending_count()):
    titles["user_management"] = f"User management ({n})"
pages = make_pages(allowed, titles=titles)
page = st.navigation(list(pages.values()), position="top")
auth.user_bar(user)
key = next(k for k, p in pages.items() if p is page)
if key not in allowed:
    st.error(auth.DENIED, icon="🔒")
    st.stop()
if key != "user_management":
    ui.render_filter_bar()
page.run()
