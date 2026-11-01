"""Shared dashboard pieces: cached metric calls, global filter bar, page header,
colors and number formatting. No metric logic lives here."""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src import metrics  # noqa: E402

# --- Colors (same meaning on every page) -------------------------------------
# Handling paths use the three categorical slots validated for all-pairs
# colour-blind separation; languages use slots 5-8 of the same palette.
PATH_COLORS = {
    "translation_tool": "#1baf7a",
    "interpreter_line": "#2a78d6",
    "no_support": "#eb6834",
    "native_exempt": "#a3a29b",
}
PATH_LABELS = {
    "translation_tool": "Translation tool",
    "interpreter_line": "Interpreter line",
    "no_support": "No support",
    "native_exempt": "Native speaker (exempt)",
}
PATH_ORDER = ["translation_tool", "interpreter_line", "no_support", "native_exempt"]
NOT_ADOPTED_COLOR = "#d6d4cc"   # neutral remainder of the Overview adoption donut
RATE_COLORS = {
    "tool_adoption": PATH_COLORS["translation_tool"],
    "interpreter_compliance": PATH_COLORS["interpreter_line"],
    "supported_rate": "#52514e",
}
RATE_LABELS = {
    "tool_adoption": "Tool adoption",
    "interpreter_compliance": "Interpreter compliance",
    "supported_rate": "Supported rate",
}
RATE_DEFINITIONS = {
    "tool_adoption": "Tool-enabled eligible calls handled with the translation tool.",
    "interpreter_compliance": "Eligible calls before the agent's tool was enabled that used the interpreter line.",
    "supported_rate": "All eligible calls handled the expected way (tool if enabled, else interpreter).",
}
LANGUAGE_COLORS = {"Spanish": "#e87ba4", "Portuguese": "#008300",
                   "Mandarin": "#6250d6", "Vietnamese": "#e34948"}
TEAM_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
ROUTING_COLORS = {"Native agent": "#a3a29b", "Overflow to non-native": "#6250d6"}

PRESETS = ["All time", "Last 7 days", "Last 30 days", "Last 90 days", "Month to date",
           "Since rollout", "Custom"]


# --- Data access -------------------------------------------------------------

# Hash of the code and data, set by the entry point (streamlit_app.code_version).
# Passed to every cached loader so a deploy never reuses results cached by an
# older version.
VERSION = None
OPTION_KEYS = {"min_date", "max_date", "first_rollout_date", "teams", "supervisors", "languages",
               "team_supervisors"}


@st.cache_resource(show_spinner=False)
def _connection(version):
    """One DuckDB connection over the committed Parquet files."""
    return metrics.connect()


@st.cache_data(show_spinner=False)
def _cached(fn_name, filter_args, extra, version):
    con = _connection(version).cursor()   # a cursor per call keeps DuckDB thread-safe
    try:
        return getattr(metrics, fn_name)(*filter_args, con=con, **dict(extra))
    finally:
        con.close()


def q(fn, f, **kwargs) -> pd.DataFrame:
    """Call a src.metrics function with the active filters, limited to the signed-in
    user's scope, cached. Every page gets its data through here."""
    return _cached(fn.__name__, scoped(f).args(), tuple(sorted(kwargs.items())), VERSION)


@st.cache_data(show_spinner=False)
def _options(version) -> dict:
    con = _connection(version).cursor()
    try:
        return metrics.filter_options(con=con)
    finally:
        con.close()


def options() -> dict:
    """Filter bar values. Recomputed if the cache holds a dict from an older version."""
    opts = _options(VERSION)
    if not OPTION_KEYS <= set(opts):
        _options.clear()
        opts = _options(VERSION)
    return opts


def team_colors() -> dict:
    """Fixed color per team, so a filter never repaints the remaining teams."""
    return dict(zip(options()["teams"], TEAM_PALETTE))


# --- Access scope ------------------------------------------------------------

def role() -> str:
    return st.session_state["user"]["role"]


def user_scope():
    """(team, supervisor) the signed-in user is limited to, or None for all teams.
    Supervisors see only their own team; admins and viewers see all teams."""
    user = st.session_state.get("user")
    if not user or user.get("role") not in ("admin", "supervisor", "viewer"):
        raise PermissionError("No signed-in user.")
    if user["role"] != "supervisor":
        return None
    return user["team"], options()["team_supervisors"].get(user["team"])


def scoped(f):
    """Filters with the user's forced team applied, whatever session_state says."""
    scope = user_scope()
    if scope is None:
        return f
    team, supervisor = scope
    return replace(f, teams=(team,), supervisors=(supervisor,) if supervisor else None)


# --- Filters -----------------------------------------------------------------

@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    teams: tuple | None      # None = all
    supervisors: tuple | None
    languages: tuple

    def args(self):
        """Positional filter arguments for src.metrics functions."""
        as_list = lambda v: None if v is None else list(v)  # noqa: E731
        return (self.start, self.end, as_list(self.teams), as_list(self.supervisors),
                list(self.languages))


def preset_range(preset, opts):
    """(start, end) for a preset, relative to the last date in the data."""
    lo, hi = opts["min_date"], opts["max_date"]
    starts = {
        "All time": lo,
        "Last 7 days": hi - timedelta(days=6),
        "Last 30 days": hi - timedelta(days=29),
        "Last 90 days": hi - timedelta(days=89),
        "Month to date": hi.replace(day=1),
        "Since rollout": opts["first_rollout_date"],
    }
    return max(starts[preset], lo), hi


# Filter values live in these session_state keys. Widgets use separate "_w_"
# keys that are refreshed from them on every run, because Streamlit can drop a
# widget's own state (e.g. inside an unopened popover) when the page changes.
FILTER_KEYS = ["preset", "start_date", "end_date", "teams", "supervisors", "languages"]


def _widget_changed(key):
    """Copy a widget's new value into its filter key, then apply side effects."""
    ss = st.session_state
    ss[key] = ss[f"_w_{key}"]
    if key == "preset" and ss.preset != "Custom":
        ss.start_date, ss.end_date = preset_range(ss.preset, options())
    elif key in ("start_date", "end_date"):
        ss.preset = "Custom"


LIST_KEYS = ("teams", "supervisors", "languages")
STALE_KEYS = ["sites", "_w_sites"]   # filters removed in earlier versions


def _defaults(opts) -> dict:
    """Default value for every filter key."""
    return {"preset": "All time", "start_date": opts["min_date"], "end_date": opts["max_date"],
            **{key: list(opts[key]) for key in LIST_KEYS}}


def _reset():
    defaults = _defaults(options())   # read options first, so a failure leaves state untouched
    for key in FILTER_KEYS:
        st.session_state[key] = defaults[key]


def _repair_state(opts):
    """Initialize filter keys that are missing or no longer valid (e.g. a session
    carried over from an older version), and drop keys of removed filters."""
    ss, defaults = st.session_state, _defaults(opts)
    for key in STALE_KEYS:
        ss.pop(key, None)
    if ss.get("preset") not in PRESETS:
        ss.preset = defaults["preset"]
    for key in ("start_date", "end_date"):
        value = ss.get(key)
        if not isinstance(value, date) or not opts["min_date"] <= value <= opts["max_date"]:
            ss[key] = defaults[key]
    for key in LIST_KEYS:
        value = ss.get(key)
        valid = [v for v in value if v in opts[key]] if isinstance(value, (list, tuple)) else []
        # Keep a deliberate empty selection; replace one that only held stale values.
        ss[key] = valid if valid or value == [] else defaults[key]


FILTER_BAR_CSS = """
<style>
/* No sidebar on a laptop: the menu is on top and filters live in this bar.
   On a phone Streamlit moves the menu into a slide-out panel, so leave it. */
.st-key-filter_bar { padding: 0.5rem 0.75rem 0.6rem; }
/* Phone: two controls per row instead of one tall stack; date range full width. */
@media (max-width: 640px) {
  .st-key-filter_bar [data-testid="stHorizontalBlock"] { flex-flow: row wrap; gap: 0.5rem; }
  .st-key-filter_bar [data-testid="stColumn"] { flex: 1 1 calc(50% - 0.5rem) !important;
      min-width: calc(50% - 0.5rem) !important; width: calc(50% - 0.5rem) !important; }
  .st-key-filter_bar [data-testid="stColumn"]:first-child { flex-basis: 100% !important;
      min-width: 100% !important; width: 100% !important; }
}
.st-key-filter_bar [data-testid="stWidgetLabel"] { min-height: 1.1rem; }
.st-key-filter_bar [data-testid="stPopover"] button p { white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
</style>
"""


def _summary(label, selected, everything):
    """Popover button text, e.g. 'Team: All', 'Team: Echo', 'Team: 2 of 6'."""
    if set(selected) == set(everything):
        value = "All"
    elif len(selected) == 1:
        value = selected[0]
    else:
        value = f"{len(selected)} of {len(everything)}" if selected else "None"
    return f"{label}: {value}"


def render_filter_bar():
    """Draw the global filter bar and store the active Filters in session_state.

    Rendered once by the entry point above every page, so selections carry
    across pages. One row on a laptop; Streamlit stacks the columns on a phone.
    """
    opts = options()
    ss = st.session_state
    _repair_state(opts)
    scope = user_scope()
    if scope:   # a supervisor's Team and Supervisor filters are locked to their team
        ss.teams, ss.supervisors = [scope[0]], [s for s in scope[1:] if s]

    for key in FILTER_KEYS:
        ss[f"_w_{key}"] = ss[key]
    widget = lambda key: dict(key=f"_w_{key}", on_change=_widget_changed, args=(key,))  # noqa: E731

    st.html(FILTER_BAR_CSS)
    with st.container(border=True, key="filter_bar"):
        cols = st.columns([1.2, 1.35, 1.35, 1, 1.2, 1.15, 0.65], gap="small",
                          vertical_alignment="bottom")
        cols[0].selectbox("Date range", PRESETS, **widget("preset"),
                          help=f"Presets count back from the last day of data "
                               f"({opts['max_date']:%b %d, %Y}).")
        kw = dict(min_value=opts["min_date"], max_value=opts["max_date"], format="YYYY-MM-DD")
        cols[1].date_input("Start", **widget("start_date"), **kw)
        cols[2].date_input("End", **widget("end_date"), **kw)
        for col, key, label in ((cols[3], "teams", "Team"), (cols[4], "supervisors", "Supervisor"),
                                (cols[5], "languages", "Language")):
            locked = bool(scope) and key in ("teams", "supervisors")
            with col.popover(_summary(label, ss[key], opts[key]), width="stretch", disabled=locked,
                             help="Locked to your team" if locked else None):
                st.multiselect(label, opts[key], **widget(key), placeholder=f"Choose {key}")
        cols[6].button("Reset", on_click=_reset, width="stretch", help="Reset all filters",
                       key="reset_filters")

    errors = []
    if ss.start_date > ss.end_date:
        errors.append("Start date is after end date. Pick a start date on or before the end date.")
    for key, label in (("teams", "team"), ("supervisors", "supervisor"), ("languages", "language")):
        if not ss[key]:
            errors.append(f"Select at least one {label}.")

    all_or = lambda key: None if set(ss[key]) == set(opts[key]) else tuple(sorted(ss[key]))  # noqa: E731
    ss.filters = scoped(Filters(ss.start_date, ss.end_date, all_or("teams"), all_or("supervisors"),
                                tuple(l for l in opts["languages"] if l in ss.languages)))
    ss.filter_errors = errors


# --- Page furniture ------------------------------------------------------------

def _describe(values, everything):
    if values is None or set(values) == set(everything):
        return "all"
    return ", ".join(values) or "none"


def page_header(title, subtitle=None, require_data=True, centered=False,
                show_filters=True, art=None) -> Filters:
    """Optional decorative art (HTML/SVG) above the title, title, active filter summary
    (unless show_filters is False), and stops the page if filters are invalid or
    return no eligible calls. Returns the active Filters."""
    if art:
        st.html(art)
    st.title(title, text_alignment="center" if centered else "left")
    f = st.session_state.filters
    if show_filters:
        opts = options()
        days = (f.end - f.start).days + 1
        st.markdown(
            f"**{f.start:%b %d, %Y} – {f.end:%b %d, %Y}** ({days:,} days, {st.session_state.preset.lower()})"
            if days > 0 else "**Invalid date range**")
        st.caption(f"Teams: {_describe(f.teams, opts['teams'])}"
                   f" · Supervisors: {_describe(f.supervisors, opts['supervisors'])}"
                   f" · Languages: {_describe(f.languages, opts['languages'])}")
    if subtitle:
        st.caption(subtitle)

    if st.session_state.filter_errors:
        for e in st.session_state.filter_errors:
            st.warning(e)
        st.stop()
    if require_data and q(metrics.kpi_summary, f).iloc[0]["eligible_calls"] == 0:
        no_data()
        st.stop()
    return f


def no_data(what="these filters"):
    st.info(f"No data for {what}. Try a wider date range or add teams, supervisors or languages "
            "in the filter bar.", icon="🔎")


def footnote():
    st.divider()
    st.caption("Team and supervisor use each agent's current team; team history isn't modeled. "
               "Eligible = in-scope language call handled by a non-native agent. "
               "All data is synthetic.")


# --- Formatting and chart helpers -------------------------------------------------

def pct(x, digits=1):
    return "—" if pd.isna(x) else f"{x:.{digits}%}"


def money(x):
    return "—" if pd.isna(x) else f"${x:,.0f}"


def num(x):
    return "—" if pd.isna(x) else f"{x:,.0f}"


def style(fig, height=380, pct_axis=False, legend=True):
    """Common Plotly layout: compact margins, horizontal legend on top, light grid."""
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
        showlegend=legend, hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
    )
    fig.update_xaxes(showgrid=False, title_text="")
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False, title_text="")
    if pct_axis:
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    if fig.layout.barmode != "group":
        # Plotly Express gives each color its own offset group, which newer
        # plotly.js places side by side; one shared group keeps bars stacked/centered.
        fig.update_traces(offsetgroup="shared", selector=dict(type="bar"))
    return fig


def mark_dates(fig, rows, label_col, date_col, start=None, end=None):
    """Dotted vertical marker with a small label for each date (e.g. team rollouts).
    Dates outside start..end are skipped so they don't stretch the axis."""
    if start is not None:
        d = pd.to_datetime(rows[date_col])
        rows = rows[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    for i, r in enumerate(rows.itertuples()):
        x = pd.Timestamp(getattr(r, date_col))
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
                      line=dict(color="rgba(110,110,110,0.6)", width=1, dash="dot"))
        fig.add_annotation(x=x, y=1 - 0.07 * (i % 2), yref="paper", text=str(getattr(r, label_col)),
                           showarrow=False, xanchor="left", font=dict(size=11, color="#6b6a65"))
    return fig


def show(fig, width="stretch"):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width=width, config={"displayModeBar": False})


def path_label(df, col="handling_path"):
    """Copy of df with a readable handling-path label column for charts."""
    df = df.copy()
    df["Handling path"] = df[col].map(PATH_LABELS).fillna(df[col])
    return df


def rate_lines(df, x, rates=tuple(RATE_LABELS)):
    """Line chart of rate columns over x, using the shared rate colors."""
    fig = go.Figure()
    for r in rates:
        fig.add_scatter(x=df[x], y=df[r], name=RATE_LABELS[r], mode="lines+markers",
                        line=dict(color=RATE_COLORS[r], width=2,
                                  dash="dash" if r == "supported_rate" else "solid"),
                        marker=dict(size=6), hovertemplate="%{y:.1%}")
    return fig
