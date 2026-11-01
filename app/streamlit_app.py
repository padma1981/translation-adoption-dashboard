"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
Nothing but the sign-in screens is shown until a user is signed in (see auth.py).
The top menu (only the pages the user's role allows) and the filter bar are drawn
here once, so filters carry across every page.
"""

from dataclasses import replace
from pathlib import Path
import base64
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
    "Calls with no language support (neither the tool nor the interpreter line) are excluded. "
    "Adopted the tool: a translation session is linked to the call. "
    "Used the interpreter: the interpreter line instead of the tool.")

REPEAT_HELP = ("Agents whose tool was enabled but who handled eligible calls with the interpreter line "
               "instead of the translation tool, in the selected period and filters. "
               "Calls with no language support are excluded.")

MONTH_HELP = ("Tool adoption per month: tool calls / (tool + interpreter calls) among tool-enabled "
              "eligible calls; no-support calls are excluded. Click a bar, or pick a month below, "
              "to see that month by language.")

LANGUAGE_HELP = ("Language calls: all calls in that language, native and non-native agents. "
                 "Eligible calls: tool-enabled eligible calls handled with the tool or the "
                 "interpreter line (no-support calls excluded). Tool %: used the tool / eligible.")

# Decorative header art: a headset between "Hola" and "Hello" speech bubbles, with the
# four language colors. st.html strips inline <svg>, so it is shown as a data-URI image.
HEADER_SVG = """<svg viewBox="0 0 240 112" width="240" height="112" xmlns="http://www.w3.org/2000/svg">
  <rect x="6" y="10" width="76" height="38" rx="14" fill="#0F9D8A"/>
  <path d="M58 47 L74 62 L70 47 Z" fill="#0F9D8A"/>
  <text x="44" y="36" text-anchor="middle" font-family="sans-serif" font-size="19"
        font-weight="700" fill="#FFFFFF">Hola</text>
  <rect x="158" y="10" width="76" height="38" rx="14" fill="#F4A261"/>
  <path d="M182 47 L166 62 L170 47 Z" fill="#F4A261"/>
  <text x="196" y="36" text-anchor="middle" font-family="sans-serif" font-size="19"
        font-weight="700" fill="#1F2937">Hello</text>
  <path d="M90 76 A30 30 0 0 1 150 76" fill="none" stroke="#1F2937" stroke-width="7"
        stroke-linecap="round"/>
  <rect x="82" y="68" width="16" height="28" rx="7" fill="#1F2937"/>
  <rect x="142" y="68" width="16" height="28" rx="7" fill="#1F2937"/>
  <path d="M150 92 Q150 106 130 106" fill="none" stroke="#1F2937" stroke-width="4"
        stroke-linecap="round"/>
  <circle cx="126" cy="106" r="5" fill="#F4A261"/>
  <circle cx="100" cy="22" r="4" fill="#e87ba4"/>
  <circle cx="114" cy="16" r="4" fill="#008300"/>
  <circle cx="126" cy="16" r="4" fill="#6250d6"/>
  <circle cx="140" cy="22" r="4" fill="#e34948"/>
</svg>"""
HEADER_ART = ('<div class="page-art" aria-hidden="true"><img alt="" src="data:image/svg+xml;base64,'
              + base64.b64encode(HEADER_SVG.encode()).decode() + '"></div>')

TOP_CARD_HEIGHT = 410      # min height of the top-row cards (donut, Trends)
BOTTOM_CARD_HEIGHT = 440   # min height of the bottom-row cards (month, language)
CARDS = ["card_adoption", "card_trends", "card_month", "card_language"]
SECTION_CSS = f"""
<style>
/* Decorative art above the centered title; smaller on a phone. */
.page-art {{ display: flex; justify-content: center; margin-bottom: -0.75rem; }}
.page-art img {{ height: 100px; width: auto; }}
/* Extra space between the title and the first row of cards. */
.title-gap {{ height: 12px; }}
/* One chart-card style for all four cards; cards in a row share a min height. */
{", ".join(f".st-key-{c}" for c in CARDS)} {{
  background: #FFFFFF;
  border: 1px solid #94A3B8; border-radius: 14px;
  padding: 12px 14px 10px; box-sizing: border-box;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.18), 0 2px 6px rgba(15, 23, 42, 0.10);
  overflow: visible;
}}
.st-key-card_adoption, .st-key-card_trends {{ min-height: {TOP_CARD_HEIGHT}px; }}
.st-key-card_month, .st-key-card_language {{ min-height: {BOTTOM_CARD_HEIGHT}px; }}
@media (max-width: 640px) {{
  .page-art img {{ height: 56px; }}
  .title-gap {{ height: 0; }}
  {", ".join(f".st-key-{c}" for c in CARDS)} {{ min-height: 0; }}
}}
</style>
<div class="title-gap"></div>
"""
DONUT_HEIGHT = 280
TRENDS_HEIGHT = 300
MONTH_HEIGHT = 300
DRILL_HEIGHT = 236         # leaves room for the Back button in the same card
TABLE_HEIGHT = 330         # language table when split by queue (scrolls inside)
TOP_AGENTS = 10
MISSED_COLOR = "#F4A261"
ADOPTED_COLOR = "#0F9D8A"      # teal
NOT_ADOPTED_COLOR = "#F4A261"  # soft orange
MUTED = "#6b6a65"
DEFAULT_MIN_MISSED = 3
ALL_MONTHS = "All months"
CHART_CONFIG = {"displayModeBar": False}


def with_filters(df, f):
    """Copy of df with the active filters as columns, so a CSV can be reproduced."""
    return df.assign(start_date=f.start, end_date=f.end,
                     teams="; ".join(f.teams or ["all"]),
                     supervisors="; ".join(f.supervisors or ["all"]),
                     languages="; ".join(f.languages))


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
                      legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.02, yanchor="top",
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
                       "Eligible calls (excl. no support): %{customdata[4]:,}<br>"
                       "Adoption: %{customdata[5]:.1%}<extra></extra>")))
    fig.update_layout(
        height=TRENDS_HEIGHT, bargap=0.3, hovermode="closest", showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10), font=dict(size=12),
        xaxis=dict(title_text="Missed calls (interpreter line)", gridcolor="rgba(31,41,55,0.10)",
                   zeroline=False, range=[0, agents["missed_calls"].max() * 1.15]),
        yaxis=dict(autorange="reversed", showgrid=False, automargin=True))
    return fig


def adoption_bars(df, x, height, colors=ADOPTED_COLOR, empty_text="Before<br>rollout"):
    """Vertical adoption % bars with the % on each bar and call counts in the hover.
    Bars with no tool-enabled calls are labeled empty_text instead of 0%."""
    custom = df[["enabled_tool_calls", "enabled_interpreter_calls", "counted_calls"]]
    fig = go.Figure(go.Bar(
        x=df[x], y=df["tool_adoption"], customdata=custom, marker=dict(color=colors, line=dict(width=0)),
        texttemplate="%{y:.1%}", textposition="outside", cliponaxis=False,
        textfont=dict(size=12, color="#1F2937"),
        hovertemplate=("<b>%{x}</b><br>Adoption: %{y:.1%}<br>Used the tool: %{customdata[0]:,}<br>"
                       "Used the interpreter: %{customdata[1]:,}<br>"
                       "Eligible calls (excl. no support): %{customdata[2]:,}<extra></extra>")))
    for label in df.loc[df["tool_adoption"].isna(), x]:
        fig.add_annotation(x=label, y=0, yanchor="bottom", text=empty_text, showarrow=False,
                           font=dict(size=11, color=MUTED))
    fig.update_layout(
        height=height, bargap=0.35, hovermode="closest", showlegend=False, dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=16, b=10), font=dict(size=12),
        xaxis=dict(type="category", showgrid=False, fixedrange=True),
        yaxis=dict(range=[0, 1.12], tickformat=".0%", gridcolor="rgba(31,41,55,0.10)",
                   zeroline=False, fixedrange=True))
    return fig


def min_missed_slider(max_missed):
    """Slider for the minimum missed calls, kept within 1..max_missed as filters change."""
    if max_missed <= 1:   # a slider needs min < max
        return 1
    current = st.session_state.get("min_missed", DEFAULT_MIN_MISSED)
    st.session_state.min_missed = min(max(int(current), 1), max_missed)
    return st.slider("Minimum missed calls", min_value=1, max_value=max_missed, step=1,
                     key="min_missed")


def adoption_section(f, split, no_support):
    adopted = split.set_index("slice").loc["Adopted the tool"]
    st.subheader("Adoption Percentage", anchor=False)
    with st.container(key="card_adoption"):
        ui.show(adoption_donut(split, adopted["share"]))
        st.markdown(f"**{int(adopted['calls']):,}** of **{int(split['calls'].sum()):,}** "
                    "eligible calls adopted the tool", help=ELIGIBILITY_HELP,
                    text_alignment="center")
        st.caption(f"{no_support:,} eligible calls had no language support and aren't counted",
                   text_alignment="center")
    st.download_button("Download CSV", with_filters(split, f).to_csv(index=False),
                       "adoption_split.csv", "text/csv", icon=":material/download:")


def trends_section(f):
    all_missed = ui.q(metrics.repeat_non_users, f, min_missed=1, exclude_no_support=True)
    st.subheader("Trends", anchor=False, help=REPEAT_HELP)
    with st.container(key="card_trends"):
        if all_missed.empty:
            st.info("No tool-enabled agent used the interpreter instead of the tool for these "
                    "filters.", icon="🎉")
            return
        min_missed = min_missed_slider(int(all_missed["missed_calls"].max()))
        agents = all_missed[all_missed["missed_calls"] >= min_missed].reset_index(drop=True)
        ui.show(repeat_non_users_chart(agents.head(TOP_AGENTS)))
    st.markdown(f"**{len(agents):,}** agents with **{int(agents['missed_calls'].sum()):,}** "
                f"missed calls (at least {min_missed} each)")
    if len(agents) > TOP_AGENTS:
        st.caption(f"Showing {TOP_AGENTS} of {len(agents):,} agents; the CSV includes all.")
    calls = ui.q(metrics.missed_call_details, f, min_missed=int(min_missed), exclude_no_support=True)
    st.download_button("Download CSV", calls.to_csv(index=False),
                       f"missed_calls_{f.start:%Y-%m-%d}_to_{f.end:%Y-%m-%d}.csv",
                       "text/csv", icon=":material/download:", key="missed_calls_csv")


def _set_month(label):
    st.session_state.ov_month = label


def _month_picked():
    pick = st.session_state.ov_month_pick
    st.session_state.ov_month = None if pick == ALL_MONTHS else pick


MONTH_CSV_COLUMNS = {"enabled_tool_calls": "used_the_tool",
                     "enabled_interpreter_calls": "used_the_interpreter",
                     "counted_calls": "eligible_calls_excl_no_support",
                     "enabled_no_support_calls": "no_support_calls_excluded",
                     "tool_adoption": "adoption"}


def month_section(f):
    """Adoption % per month; a click on a bar (or the month dropdown) drills into
    that month by language, with a Back button."""
    ss = st.session_state
    months = ui.q(metrics.overview_adoption, f, grain="month")
    months["month"] = pd.to_datetime(months["month_start"]).dt.strftime("%b %Y")
    with_rate = months.loc[months["tool_adoption"].notna(), "month"].tolist()
    if ss.get("ov_month") not in with_rate:   # also clears a month the filters dropped
        ss.ov_month = None

    st.subheader("Adoption by Month", anchor=False, help=MONTH_HELP)
    with st.container(key="card_month"):
        if ss.ov_month is None:
            event = st.plotly_chart(adoption_bars(months, "month", MONTH_HEIGHT), width="stretch",
                                    config=CHART_CONFIG, on_select="rerun", selection_mode="points",
                                    key="month_chart")
            points = (event or {}).get("selection", {}).get("points", [])
            picked = [p.get("x") for p in points if p.get("x") in with_rate]
            if picked:
                ss.ov_month = picked[0]
                st.rerun()
            shown = months[["month_start", "month"] + list(MONTH_CSV_COLUMNS)].rename(
                columns=MONTH_CSV_COLUMNS)
            name = "adoption_by_month.csv"
        else:
            st.button("Back to all months", on_click=_set_month, args=(None,),
                      icon=":material/arrow_back:", key="month_back")
            start = pd.Timestamp(months.set_index("month").loc[ss.ov_month, "month_start"])
            end = start + pd.offsets.MonthEnd(0)
            month_f = replace(f, start=max(start.date(), f.start), end=min(end.date(), f.end))
            langs = ui.q(metrics.overview_adoption, month_f, by="language")
            colors = [ui.LANGUAGE_COLORS.get(lang, ADOPTED_COLOR) for lang in langs["language"]]
            st.caption(f"**{ss.ov_month}** by language")
            ui.show(adoption_bars(langs, "language", DRILL_HEIGHT, colors=colors,
                                  empty_text="No tool-enabled<br>calls"))
            shown = langs[["language"] + list(MONTH_CSV_COLUMNS)].rename(columns=MONTH_CSV_COLUMNS)
            shown.insert(0, "month", ss.ov_month)
            name = f"adoption_{start:%Y-%m}_by_language.csv"
        ss.ov_month_pick = ss.ov_month or ALL_MONTHS   # keep the dropdown in step with clicks
        st.selectbox("Month", [ALL_MONTHS] + with_rate, key="ov_month_pick",
                     on_change=_month_picked, help="Same as clicking a bar (handy on touch screens).")
    st.download_button("Download CSV", with_filters(shown, f).to_csv(index=False), name,
                       "text/csv", icon=":material/download:", key="month_csv")


LANGUAGE_COLUMNS = {"language": "Language", "queue": "Queue", "language_calls": "Calls",
                    "counted_calls": "Eligible", "enabled_tool_calls": "Tool",
                    "enabled_interpreter_calls": "Interpreter", "tool_adoption": "Tool %"}
# Short headers keep the table, Tool % bar and label included, inside a half-width card;
# the full meaning is in each header's tooltip. Widths in pixels; Tool % gets what's left
# of a ~545px card (less when the Queue column is shown).
LANGUAGE_HEADERS = {
    "Language": (76, None), "Queue": (106, None),
    "Calls": (64, "Language calls: all calls in that language (native and non-native agents)"),
    "Eligible": (66, "Eligible calls: tool-enabled eligible calls, excluding no support"),
    "Tool": (56, "Used the tool"),
    "Interpreter": (80, "Used the interpreter"),
}


def language_section(f):
    """Calls vs tool use per language (optionally by queue) with a Total row."""
    st.subheader("Calls vs Tool Use by Language", anchor=False, help=LANGUAGE_HELP)
    with st.container(key="card_language"):
        by_queue = st.toggle("Split by queue", key="ov_split_queue")
        table = ui.q(metrics.language_tool_use, f, by_queue=by_queue)
        shown = table[[c for c in LANGUAGE_COLUMNS if c in table.columns]].rename(
            columns=LANGUAGE_COLUMNS)
        shown["Tool %"] = shown["Tool %"] * 100
        config = {}
        for col, (width, help_text) in LANGUAGE_HEADERS.items():
            if col in ("Language", "Queue"):
                config[col] = st.column_config.Column(width=width)
            else:   # thousands separators; numbers are right-aligned
                config[col] = st.column_config.NumberColumn(format="localized", width=width,
                                                            help=help_text)
        config["Tool %"] = st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f%%", width=92 if by_queue else 190,
            help="Used the tool / eligible calls")
        st.dataframe(shown, hide_index=True, width="stretch",
                     height=TABLE_HEIGHT if by_queue else "auto", column_config=config)
    csv = table.rename(columns={"counted_calls": "eligible_calls_excl_no_support",
                                "tool_adoption": "tool_pct"})
    st.download_button("Download CSV", with_filters(csv, f).to_csv(index=False),
                       "calls_vs_tool_use_by_language.csv" if not by_queue
                       else "calls_vs_tool_use_by_language_and_queue.csv",
                       "text/csv", icon=":material/download:", key="language_csv")


def overview():
    """2 x 2 grid: adoption donut and Trends on top, adoption by month and the language
    table below, each with a CSV download for the active filters. No-support calls are
    left out of every Overview number. Viewers see only the donut and its CSV.
    On a phone the columns stack in reading order."""
    f = ui.page_header("Translation Tool Adoption", centered=True, show_filters=False, art=HEADER_ART)
    split = ui.q(metrics.adoption_split, f, exclude_no_support=True)
    if int(split["calls"].sum()) == 0:
        ui.no_data("tool-enabled eligible calls in this selection (the tool may not be "
                   "rolled out yet for these teams and dates)")
        st.stop()
    no_support = int(ui.q(metrics.kpi_summary, f).iloc[0]["enabled_no_support_calls"])

    st.html(SECTION_CSS)
    top_left, top_right = st.columns(2, gap="large")
    with top_left:
        adoption_section(f, split, no_support)
    if ui.role() == "viewer":   # no agent names, trends or breakdowns for viewers
        ui.footnote()
        return
    with top_right:
        trends_section(f)
    bottom_left, bottom_right = st.columns(2, gap="large")
    with bottom_left:
        month_section(f)
    with bottom_right:
        language_section(f)
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
