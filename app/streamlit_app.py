"""Entry point and Overview page.

Run with: streamlit run app/streamlit_app.py
Nothing but the sign-in screens is shown until a user is signed in (see auth.py).
The top menu (only the pages the user's role allows), the account menu at its right
end and, on every page but the Overview, the Filters menu are drawn here once, so
filters carry across pages. The Overview has its own date-range picker.
"""

from dataclasses import replace
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

MONTH_HELP = ("Tool adoption per month: tool calls / (tool + interpreter calls) among tool-enabled "
              "eligible calls; no-support calls are excluded. Click a bar, or pick a month below, "
              "to see that month by language.")

LANGUAGE_HELP = ("Language calls: all calls in that language, native and non-native agents. "
                 "Eligible calls: tool-enabled eligible calls handled with the tool or the "
                 "interpreter line (no-support calls excluded). Tool %: used the tool / eligible.")

AHT_HELP = ("Average handle time (talk + hold + wrap-up) in the selected dates. "
            "Native speaker: Spanish, Portuguese, Mandarin or Vietnamese calls handled by an agent "
            "native in that language. Translation tool / Interpreter: eligible calls handled with "
            "the translation tool or the interpreter line. No-support calls are excluded.")

FTE_HELP = ("Hours saved: for each language, tool calls x (interpreter AHT - tool AHT) in that "
            "language over the selected dates, summed, so the language mix doesn't distort it. "
            "FTE saved = hours saved / ({h} hours x weeks in the selected dates), where one FTE is "
            "one agent working a {h}-hour week and weeks = days / 7. Monthly bars apply the same "
            "per-language AHT difference to each month's tool calls, counting only that month's "
            "days inside the selected dates.")

FEES_HELP = ("Fees saved: for each language, tool calls x the average interpreter cost per "
             "interpreter call in that language (eligible calls handled with the interpreter line "
             "in the selected dates), summed. Same assumption as Agent Time Saved: each tool call "
             "would otherwise have used the interpreter line. Interpreters are billed at "
             "${rate:.2f} per minute. No-support calls are excluded. Monthly bars apply the same "
             "per-language average cost to each month's tool calls.")

SPEND_HELP = ("Interpreter line use per month, split by whether the agent's translation tool was "
              "already enabled on the call date. 'Tool was available' is the avoidable part: it "
              "should shrink as adoption grows. Billed at ${rate:.2f} per minute.")

CARDS = ["card_adoption", "card_month", "card_language", "card_aht", "card_fte", "card_fees",
         "card_spend"]
ROWS = ["row_top", "row_bottom", "row_third"]
SECTION_CSS = ui.card_css(CARDS, ROWS) + f"""
<style>
/* Headline above the handle-time chart; large FTE and fees numbers; spend figures. */
.aht-headline {{ text-align: center; font-size: 1.15rem; font-weight: 700; color: {ui.NAVY};
  margin: 2px 0 0; }}
.big-number {{ text-align: center; font-size: 2.8rem; font-weight: 800; color: {ui.TEAL};
  line-height: 1.1; margin: 4px 0 2px; }}
.big-number span {{ font-size: 1.2rem; font-weight: 700; color: {ui.NAVY}; }}
.spend-figures {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 0.4rem 2.5rem;
  margin: 2px 0 4px; color: #52514e; font-size: 0.95rem; }}
.spend-figures b {{ color: {ui.NAVY}; font-size: 1.25rem; margin-right: 0.3rem; }}
@media (max-width: 640px) {{
  .big-number {{ font-size: 2.2rem; }}
}}
</style>
"""
DONUT_HEIGHT = 280
AHT_HEIGHT = 300
FTE_MONTH_HEIGHT = 200   # also the fees-by-month chart, so the two cards match
SPEND_HEIGHT = 320
MONTH_HEIGHT = 300
DRILL_HEIGHT = 236         # leaves room for the Back button in the same card
TABLE_HEIGHT = 330         # language table when split by queue (scrolls inside)
EMPTY_BAR_HEIGHT = 0.08        # grey stub for a month (or language) with no tool-enabled calls
ADOPTED_COLOR = ui.TEAL
NOT_ADOPTED_COLOR = ui.ORANGE
MUTED = "#6b6a65"
SPEND_COLORS = {"Tool not yet enabled": ui.NAVY, "Tool was available": ui.ORANGE}
SPEND_MEASURES = {"Spend": ("interpreter_spend_usd", "$%{y:,.0f}", "Interpreter spend ($)"),
                  "Minutes": ("interpreter_minutes", "%{y:,} min", "Interpreter minutes")}
SUPPORT_COLORS = {"Native speaker": ui.NAVY, "Translation tool": ui.TEAL,
                  "Interpreter": ui.ORANGE}
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


def adoption_bars(df, x, height, empty_text="Before<br>rollout"):
    """Vertical adoption % bars colored on the teal-to-indigo gradient, with the % in bold
    on each bar (white on dark bars, navy on light ones) and call counts in the hover.
    Bars with no tool-enabled calls get a short grey stub labeled empty_text instead of 0%."""
    colors = ui.gradient_colors(df["tool_adoption"])
    custom = df[["enabled_tool_calls", "enabled_interpreter_calls", "counted_calls"]]
    fig = go.Figure(go.Bar(
        x=df[x], y=df["tool_adoption"], customdata=custom, marker=dict(color=colors, line=dict(width=0)),
        texttemplate="%{y:.1%}", textposition="inside", insidetextanchor="end", textangle=0,
        textfont=dict(size=13, color=[ui.label_color(c) for c in colors]),
        hovertemplate=("<b>%{x}</b><br>Adoption: %{y:.1%}<br>Used the tool: %{customdata[0]:,}<br>"
                       "Used the interpreter: %{customdata[1]:,}<br>"
                       "Eligible calls (excl. no support): %{customdata[2]:,}<extra></extra>")))
    empty = df.loc[df["tool_adoption"].isna(), x]
    if len(empty):
        label = empty_text.replace("<br>", " ")
        fig.add_bar(x=empty, y=[EMPTY_BAR_HEIGHT] * len(empty), name=label,
                    marker=dict(color=ui.BEFORE_ROLLOUT_COLOR, line=dict(width=0)),
                    hovertemplate=f"<b>%{{x}}</b><br>{label}<extra></extra>")
        for value in empty:
            fig.add_annotation(x=value, y=EMPTY_BAR_HEIGHT, yanchor="bottom", text=empty_text,
                               showarrow=False, font=dict(size=11, color=MUTED))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, barmode="overlay",
        height=height, bargap=0.18, hovermode="closest", showlegend=False, dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=16, b=10), font=dict(size=12),
        xaxis=dict(type="category", showgrid=False, fixedrange=True),
        yaxis=dict(range=[0, 1.05], tickformat=".0%", gridcolor=ui.GRID,
                   zeroline=False, fixedrange=True))
    return fig


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
            event = st.plotly_chart(ui.axis_text(adoption_bars(months, "month", MONTH_HEIGHT)),
                                    width="stretch",
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
            st.caption(f"**{ss.ov_month}** by language")
            ui.show(adoption_bars(langs, "language", DRILL_HEIGHT,
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


def mmss(seconds):
    """Seconds as m:ss ('—' when missing)."""
    if pd.isna(seconds):
        return "—"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def saving_headline(handle):
    """'The tool saves Xm Ys per call vs the interpreter' from the handle-time rows."""
    aht = handle.set_index("group")["aht_sec"]
    diff = aht["Interpreter"] - aht["Translation tool"]
    if pd.isna(diff):
        return "Not enough tool and interpreter calls in these dates to compare"
    total = int(round(abs(diff)))
    span = f"{total // 60}m {total % 60}s"
    if diff >= 0:
        return f"The tool saves {span} per call vs the interpreter"
    return f"The tool takes {span} longer per call than the interpreter"


def handle_time_chart(handle):
    """Vertical AHT bars (minutes) per support type, m:ss on each bar, calls in the hover."""
    minutes = handle["aht_sec"] / 60
    top = max(float(minutes.max()) if minutes.notna().any() else 1.0, 1.0)
    step = 2 if top <= 16 else 5
    ticks = list(range(0, int(top * 1.18) + step, step))
    fig = go.Figure(go.Bar(
        x=handle["group"], y=minutes, customdata=handle[["calls", "aht_mmss"]],
        marker=dict(color=[SUPPORT_COLORS[g] for g in handle["group"]], line=dict(width=0)),
        text=handle["aht_mmss"], textposition="outside", cliponaxis=False,
        textfont=dict(size=14, color=ui.NAVY),
        hovertemplate=("<b>%{x}</b><br>Calls: %{customdata[0]:,}<br>"
                       "AHT: %{customdata[1]}<extra></extra>")))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, height=AHT_HEIGHT, bargap=0.35, showlegend=False,
        hovermode="closest", dragmode=False, margin=dict(l=10, r=10, t=24, b=10), font=dict(size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, fixedrange=True, tickfont=dict(size=13)),
        yaxis=dict(title_text="Average handle time (m:ss)", range=[0, top * 1.18],
                   tickvals=ticks, ticktext=[f"{t}:00" for t in ticks],
                   gridcolor=ui.GRID, zeroline=False, fixedrange=True))
    return fig


def handle_time_section(f):
    """Average handle time for native speakers, the translation tool and the interpreter."""
    handle = ui.q(metrics.handle_time_by_support, f)
    handle["aht_mmss"] = handle["aht_sec"].map(mmss)
    st.subheader("Handle Time by Support Type", anchor=False, help=AHT_HELP)
    with st.container(key="card_aht"):
        st.markdown(f"<p class='aht-headline'>{saving_headline(handle)}</p>",
                    unsafe_allow_html=True)
        ui.show(handle_time_chart(handle))
    csv = pd.DataFrame({"group": handle["group"], "calls": handle["calls"],
                        "aht_seconds": handle["aht_sec"].round(1), "aht_mm_ss": handle["aht_mmss"]})
    st.download_button("Download CSV", with_filters(csv, f).to_csv(index=False),
                       "handle_time_by_support_type.csv", "text/csv",
                       icon=":material/download:", key="aht_csv")


def fte_month_chart(months):
    """Small bar chart of FTE saved per month, with the value above each bar."""
    labels = pd.to_datetime(months["month_start"]).dt.strftime("%b %Y")
    top = max(float(months["fte_saved"].max()), 0.1)
    fig = go.Figure(go.Bar(
        x=labels, y=months["fte_saved"], customdata=months[["tool_calls", "hours_saved"]],
        marker=dict(color=SUPPORT_COLORS["Translation tool"], line=dict(width=0)),
        texttemplate="%{y:.2f}", textposition="outside", cliponaxis=False,
        textfont=dict(size=12, color=ui.NAVY),
        hovertemplate=("<b>%{x}</b><br>FTE saved: %{y:.2f}<br>Hours saved: %{customdata[1]:,.0f}"
                       "<br>Tool calls: %{customdata[0]:,}<extra></extra>")))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, height=FTE_MONTH_HEIGHT, bargap=0.3, showlegend=False,
        hovermode="closest", dragmode=False, margin=dict(l=10, r=10, t=20, b=10), font=dict(size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(type="category", showgrid=False, fixedrange=True),
        yaxis=dict(title_text="FTE saved", range=[0, top * 1.25], tickformat=".1f",
                   gridcolor=ui.GRID, zeroline=False, fixedrange=True))
    return fig


def fte_section(f):
    """Agent time the tool saved vs the interpreter, as FTE, with a by-month chart."""
    total = ui.q(metrics.agent_time_saved, f).iloc[0]
    months = ui.q(metrics.agent_time_saved, f, grain="month")
    st.subheader("Agent Time Saved (FTE)", anchor=False,
                 help=FTE_HELP.format(h=metrics.cfg.FTE_HOURS_PER_WEEK))
    with st.container(key="card_fte"):
        st.markdown(f"<div class='big-number'>{total['fte_saved']:.2f} <span>FTE saved</span></div>",
                    unsafe_allow_html=True)
        st.markdown(f"**{total['hours_saved']:,.0f}** hours of agent time saved on "
                    f"**{int(total['tool_calls']):,}** tool calls", text_alignment="center")
        ui.show(fte_month_chart(months))
    csv = months.assign(month=pd.to_datetime(months["month_start"]).dt.strftime("%Y-%m"))[
        ["month", "tool_calls", "hours_saved", "weeks", "fte_saved"]].round(
        {"hours_saved": 2, "weeks": 3, "fte_saved": 3})
    st.download_button("Download CSV", with_filters(csv, f).to_csv(index=False),
                       "agent_time_saved_by_month.csv", "text/csv",
                       icon=":material/download:", key="fte_csv")


def fees_month_chart(months):
    """Small teal bar chart of interpreter fees saved per month, $ labels above the bars."""
    labels = pd.to_datetime(months["month_start"]).dt.strftime("%b %Y")
    top = max(float(months["fees_saved_usd"].max()), 1.0)
    fig = go.Figure(go.Bar(
        x=labels, y=months["fees_saved_usd"], customdata=months[["tool_calls"]],
        marker=dict(color=SUPPORT_COLORS["Translation tool"], line=dict(width=0)),
        texttemplate="$%{y:,.0f}", textposition="outside", cliponaxis=False,
        textfont=dict(size=12, color=ui.NAVY),
        hovertemplate=("<b>%{x}</b><br>Fees saved: $%{y:,.0f}<br>Tool calls: %{customdata[0]:,}"
                       "<extra></extra>")))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, height=FTE_MONTH_HEIGHT, bargap=0.3, showlegend=False,
        hovermode="closest", dragmode=False, margin=dict(l=10, r=10, t=20, b=10), font=dict(size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(type="category", showgrid=False, fixedrange=True),
        yaxis=dict(title_text="Fees saved", range=[0, top * 1.25], tickprefix="$", tickformat="~s",
                   gridcolor=ui.GRID, zeroline=False, fixedrange=True))
    return fig


def fees_section(f):
    """Interpreter fees the tool saved, assuming each tool call would have used the interpreter."""
    total = ui.q(metrics.interpreter_fees_saved, f).iloc[0]
    months = ui.q(metrics.interpreter_fees_saved, f, grain="month")
    st.subheader("Interpreter Fees Saved", anchor=False,
                 help=FEES_HELP.format(rate=metrics.cfg.INTERPRETER_COST_PER_MIN))
    with st.container(key="card_fees"):
        st.markdown(f"<div class='big-number'>${total['fees_saved_usd']:,.0f} <span>saved</span></div>",
                    unsafe_allow_html=True)
        st.markdown(f"on **{int(total['tool_calls']):,}** tool calls at about "
                    f"**{ui.money2(total['avg_cost_per_interpreter_call'])}** per interpreter call",
                    text_alignment="center")
        ui.show(fees_month_chart(months))
    detail = ui.q(metrics.interpreter_fees_saved, f, grain="month", by_language=True)
    csv = detail.assign(month=pd.to_datetime(detail["month_start"]).dt.strftime("%Y-%m"))[
        ["month", "language", "tool_calls", "avg_cost_per_interpreter_call", "fees_saved_usd"]].round(
        {"avg_cost_per_interpreter_call": 2, "fees_saved_usd": 2})
    st.download_button("Download CSV", with_filters(csv, f).to_csv(index=False),
                       "interpreter_fees_saved_by_month_and_language.csv", "text/csv",
                       icon=":material/download:", key="fees_csv")


def spend_chart(months, measure):
    """Monthly interpreter spend (or minutes) stacked: tool not yet enabled, tool was available."""
    col, value_format, title = SPEND_MEASURES[measure]
    labels = pd.to_datetime(months["month_start"]).dt.strftime("%b %Y")
    fig = go.Figure()
    for name, suffix in (("Tool not yet enabled", "not_enabled"),
                         ("Tool was available", "tool_available")):
        fig.add_bar(x=labels, y=months[f"{col}_{suffix}"], name=name,
                    customdata=months[[f"interpreter_calls_{suffix}"]],
                    marker=dict(color=SPEND_COLORS[name], line=dict(color="white", width=1)),
                    hovertemplate=(f"<b>%{{x}}</b><br>{name}: {value_format}<br>"
                                   "Interpreter calls: %{customdata[0]:,}<extra></extra>"))
    fig.update_layout(
        template=ui.PLOTLY_TEMPLATE, barmode="stack", height=SPEND_HEIGHT, bargap=0.3,
        hovermode="closest", dragmode=False, margin=dict(l=10, r=10, t=30, b=10), font=dict(size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", font=dict(size=13)),
        xaxis=dict(type="category", showgrid=False, fixedrange=True),
        yaxis=dict(title_text=title, tickprefix="$" if measure == "Spend" else "", tickformat=",",
                   gridcolor=ui.GRID, zeroline=False, fixedrange=True))
    return fig


def spend_section(f):
    """Full-width card: monthly interpreter spend split by tool availability."""
    months = ui.q(metrics.interpreter_spend_by_month, f)
    st.subheader("Interpreter Spend", anchor=False,
                 help=SPEND_HELP.format(rate=metrics.cfg.INTERPRETER_COST_PER_MIN))
    with st.container(key="card_spend"):
        st.markdown(
            "<div class='spend-figures'>"
            f"<span><b>{ui.money(months['interpreter_spend_usd'].sum())}</b>total interpreter spend</span>"
            f"<span><b>{ui.money(months['interpreter_spend_usd_tool_available'].sum())}</b>"
            "spend where the tool was available</span>"
            f"<span><b>{ui.num(months['interpreter_minutes'].sum())}</b>interpreter minutes</span>"
            "</div>", unsafe_allow_html=True)
        measure = st.radio("Show", list(SPEND_MEASURES), horizontal=True, key="ov_spend_measure",
                           label_visibility="collapsed")
        ui.show(spend_chart(months, measure))
    csv = months.assign(month=pd.to_datetime(months["month_start"]).dt.strftime("%Y-%m")).drop(
        columns=["month_start"])
    csv = csv[["month"] + [c for c in csv.columns if c != "month"]]
    st.download_button("Download CSV", with_filters(csv, f).to_csv(index=False),
                       "interpreter_spend_by_month.csv", "text/csv",
                       icon=":material/download:", key="spend_csv")


def overview():
    """Executive overview for all teams, supervisors and languages (supervisors stay
    locked to their own team), with one date-range picker instead of the Filters menu.
    Rows: adoption donut | adoption by month; language table | handle time by support
    type; agent time saved (FTE) | interpreter fees saved; interpreter spend (full width).
    Each card has a CSV download. No-support calls are
    left out of every Overview number. Viewers see the whole Overview: it holds aggregate
    figures only (no agent names, agent IDs or call IDs).
    On a phone the columns stack in reading order."""
    ui.title_row("Translation Tool Adoption", banner=True,
                 subtitle="Spanish, Portuguese, Mandarin and Vietnamese calls")
    f = ui.overview_filters()
    split = ui.q(metrics.adoption_split, f, exclude_no_support=True)
    if int(split["calls"].sum()) == 0:
        st.info("No tool-enabled eligible calls in these dates (the tool may not be rolled out "
                "yet). Try a wider date range.", icon="🔎")
        st.stop()
    no_support = int(ui.q(metrics.kpi_summary, f).iloc[0]["enabled_no_support_calls"])

    st.html(SECTION_CSS)
    with st.container(key="row_top"):
        top_left, top_right = st.columns(2, gap="large")
        with top_left:
            adoption_section(f, split, no_support)
        with top_right:
            month_section(f)
    with st.container(key="row_bottom"):
        bottom_left, bottom_right = st.columns(2, gap="large")
        with bottom_left:
            language_section(f)
        with bottom_right:
            handle_time_section(f)
    with st.container(key="row_third"):
        third_left, third_right = st.columns(2, gap="large")
        with third_left:
            fte_section(f)
        with third_right:
            fees_section(f)
    spend_section(f)
    ui.footnote()


# key: (page source, title, icon, url path). Keys match auth.PAGE_ACCESS.
PAGE_SPECS = {
    "overview": (overview, "Overview", "📊", "overview"),
    "agents": ("views/1_Agents_and_Teams.py", "Agents & Teams", "👥", "Agents_and_Teams"),
    "languages": ("views/2_Languages.py", "Languages", "🗣️", "Languages"),
    "operational": ("views/unavailable.py", "Operational Impact", "⏱️", "Operational_Impact"),
    "cost": ("views/4_Cost.py", "Cost", "💵", "Cost"),
    "data_quality": ("views/unavailable.py", "Data Quality", "🧪", "Data_Quality"),
    "user_management": ("views/6_User_management.py", "User management", "🔐", "User_management"),
}
# Not in the top menu: User management opens from the admin's User management menu; the
# Cost page's content is on the Overview (its URL still works).
MENU_HIDDEN = {"user_management", "cost"}
# Removed pages: their old URLs show "This page isn't available." (views/unavailable.py).
RETIRED = {"operational", "data_quality"}


def pending_count():
    try:
        return len(users.list_users("pending"))
    except Exception:   # store unavailable: show the menu without a count
        return 0


def make_pages(visible, with_default=True):
    """All pages; those not in `visible` are registered hidden (not in the menu),
    so their URL still resolves and can show the no-access message."""
    return {key: st.Page(src, title=title, icon=icon, url_path=path,
                         default=with_default and key == "overview",
                         visibility="visible" if key in visible else "hidden")
            for key, (src, title, icon, path) in PAGE_SPECS.items()}


user = auth.gate(make_pages)
allowed = auth.allowed_pages(user)
pages = make_pages(allowed - MENU_HIDDEN)
page = st.navigation(list(pages.values()), position="top")
key = next(k for k, p in pages.items() if p is page)
is_admin = "user_management" in allowed
pending = pending_count() if is_admin else 0
um_page = pages["user_management"] if is_admin else None
auth.account_menu(user, key, pending=pending, user_management=um_page)
auth.pending_banner(pending, um_page)   # admins only, while requests are waiting
if key in RETIRED:
    page.run()
    st.stop()
if key not in allowed:
    st.error(auth.DENIED, icon="🔒")
    st.stop()
# The Overview and Agents & Teams draw their own date picker (and team dropdowns).
if key not in ("overview", "agents", "user_management"):
    ui.render_filter_bar()
page.run()
