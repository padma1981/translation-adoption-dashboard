"""Smoke tests: every dashboard page renders without errors under default and narrowed filters."""

from datetime import date

import pytest

from tests.conftest import new_app, signed_in

PAGES = [None, "views/1_Agents_and_Teams.py", "views/2_Languages.py", "views/4_Cost.py"]
AGENTS, LANGUAGES = PAGES[1], PAGES[2]
FILTER_PAGES = PAGES[2:]   # pages with the Filters menu (Agents & Teams has its own dropdowns)


def run_page(page, **state):
    """Run a page signed in as the break-glass admin, with extra session state."""
    at = signed_in(new_app())
    at.run()
    for key, value in state.items():
        at.session_state[key] = value
    if page:
        at.switch_page(page)
    at.run()
    return at


def date_line(at):
    return next(m.value for m in at.markdown if m.value.startswith("**") and "2026" in m.value)


def filter_line(at):
    return next(c.value for c in at.caption if c.value.startswith("Teams:"))


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_default_filters(page):
    at = run_page(page)
    assert not at.exception, at.exception
    assert not at.error
    if page in FILTER_PAGES:   # the Overview leaves the filter summary to the filter bar
        assert "Apr 01, 2026 – Sep 30, 2026" in date_line(at)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_narrow_filters(page):
    at = run_page(page, preset="Last 30 days", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
                  teams=["Echo"], languages=["Mandarin"])
    assert not at.exception, at.exception
    assert not at.error
    if page in FILTER_PAGES:
        assert "Sep 01, 2026 – Sep 30, 2026" in date_line(at)
        assert "Teams: Echo" in filter_line(at)


def test_start_after_end_shows_friendly_message():
    at = run_page(LANGUAGES, preset="Custom", start_date=date(2026, 9, 30), end_date=date(2026, 9, 1))
    assert not at.exception
    assert any("Start date is after end date" in w.value for w in at.warning)


def test_empty_selection_shows_friendly_message():
    at = run_page(LANGUAGES, teams=[])
    assert not at.exception
    assert any("Select at least one team" in w.value for w in at.warning)


def test_preset_sets_dates():
    at = run_page(LANGUAGES)
    at.selectbox(key="_w_preset").set_value("Last 7 days").run()
    assert at.session_state["start_date"] == date(2026, 9, 24)
    assert at.session_state["end_date"] == date(2026, 9, 30)
    at.selectbox(key="_w_preset").set_value("Since rollout").run()
    assert at.session_state["start_date"] == date(2026, 5, 1)


def test_filters_survive_page_switches():
    """Selections persist across pages even for filters inside unopened popovers."""
    at = run_page(None, teams=["Echo"], supervisors=["Cynthia Reyes"], languages=["Mandarin"])
    for page in PAGES[1:] + [PAGES[1]]:
        at.switch_page(page).run()
        assert not at.exception, at.exception
        assert at.session_state["teams"] == ["Echo"]
        assert at.session_state["supervisors"] == ["Cynthia Reyes"]
        if page in FILTER_PAGES:
            assert "Teams: Echo · Supervisors: Cynthia Reyes · Languages: Mandarin" in filter_line(at)


def test_overview_adoption_card():
    at = run_page(None)
    assert not at.exception
    assert at.title[0].value == "Translation Tool Adoption"
    assert not [m for m in at.markdown if m.value.startswith("**Apr")]   # no date range line
    assert not [c for c in at.caption if c.value.startswith("Teams:")]
    assert [h.value for h in at.subheader] == ["Adoption Percentage", "Adoption by Month",
                                               "Calls vs Tool Use by Language",
                                               "Handle Time by Support Type", "Agent Time Saved (FTE)",
                                               "Interpreter Fees Saved", "Interpreter Spend"]
    line = [m for m in at.markdown if "eligible calls adopted the tool" in m.value][0]
    assert line.value == "**8,114** of **12,836** eligible calls adopted the tool"   # no support excluded
    assert line.help.startswith("Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese")
    assert "no language support" in line.help and "excluded" in line.help
    assert any(c.value == "2,008 eligible calls had no language support and aren't counted"
               for c in at.caption)
    assert not [c for c in at.caption if "Contact center calls" in c.value]


def month_bars(at):
    import plotly.io as pio
    fig = pio.from_json(at.get("plotly_chart")[1].proto.spec)
    return fig, dict(zip(fig.data[0].x, fig.data[0].y))


def test_overview_adoption_by_month():
    at = run_page(None)
    fig, bars = month_bars(at)
    assert list(bars) == ["Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"]
    assert {k: round(v * 100, 1) for k, v in bars.items() if v is not None} == {
        "May 2026": 38.8, "Jun 2026": 57.6, "Jul 2026": 57.8, "Aug 2026": 68.0, "Sep 2026": 72.2}
    assert bars["Apr 2026"] is None
    assert [a.text for a in fig.layout.annotations] == ["Before<br>rollout"]
    # Gradient: lowest month light teal, highest deep indigo; Apr is a grey stub.
    colors = dict(zip(fig.data[0].x, fig.data[0].marker.color))
    assert colors["May 2026"] == "#7FD1C7" and colors["Sep 2026"] == "#3730A3"
    labels = dict(zip(fig.data[0].x, fig.data[0].textfont.color))
    assert labels["May 2026"] == "#1D3557" and labels["Sep 2026"] == "#FFFFFF"
    assert list(fig.data[1].x) == ["Apr 2026"] and fig.data[1].marker.color == "#CBD5E1"
    month = at.selectbox(key="ov_month_pick")
    assert month.options == ["All months", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"]


def test_overview_month_drill_down_by_dropdown():
    import plotly.io as pio
    at = run_page(None)
    at.selectbox(key="ov_month_pick").set_value("Jun 2026").run()
    assert not at.exception, at.exception
    assert at.session_state["ov_month"] == "Jun 2026"
    assert any(c.value == "**Jun 2026** by language" for c in at.caption)
    fig = pio.from_json(at.get("plotly_chart")[1].proto.spec)
    assert list(fig.data[0].x) == ["Spanish", "Portuguese", "Mandarin", "Vietnamese"]
    colors = list(fig.data[0].marker.color)
    assert colors[0] != colors[1] and "#7FD1C7" in colors and "#3730A3" in colors   # gradient
    at.button(key="month_back").click().run()
    assert at.session_state["ov_month"] is None
    assert at.selectbox(key="ov_month_pick").value == "All months"
    assert len(month_bars(at)[1]) == 6


def test_overview_month_drill_down_by_click():
    """A click on a bar arrives as the chart's selection state."""
    at = run_page(None)
    at.session_state["month_chart"] = {"selection": {"points": [{"x": "Aug 2026"}],
                                                     "point_indices": [4], "box": [], "lasso": []}}
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["ov_month"] == "Aug 2026"
    assert at.selectbox(key="ov_month_pick").value == "Aug 2026"


def test_overview_language_table():
    at = run_page(None)
    table = at.dataframe[0].value
    assert table["Language"].tolist() == ["Spanish", "Portuguese", "Mandarin", "Vietnamese", "Total"]
    assert table["Calls"].iloc[-1] == 45702
    assert [round(v, 1) for v in table["Tool %"]] == [66.1, 68.7, 53.8, 52.9, 63.2]
    at.toggle(key="ov_split_queue").set_value(True).run()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert list(table.columns[:2]) == ["Language", "Queue"]
    assert table["Queue"].tolist()[:4] == ["Billing", "Technical Support", "Account Services", "Sales"]
    assert table["Calls"].iloc[-1] == 45702 and len(table) == 17


# --- Sessions and caches carried over from an earlier version ---------------------------

def test_stale_cached_options_without_supervisors(monkeypatch):
    """A cached options dict from the version before the supervisor filter is replaced."""
    run_page(None)   # sets ui.VERSION
    import ui
    stale = {k: v for k, v in ui.metrics.filter_options().items() if k != "supervisors"}
    stale["sites"] = ["North", "South"]
    ui._options.clear()
    monkeypatch.setattr(ui.metrics, "filter_options", lambda con=None: stale)
    assert "supervisors" not in ui._options(ui.VERSION)   # the stale dict is now cached
    monkeypatch.undo()
    for page in PAGES:
        at = run_page(page)
        assert not at.exception, at.exception
        assert not at.error
    assert "supervisors" in ui._options(ui.VERSION)
    at = run_page(LANGUAGES)
    at.button(key="reset_filters").click().run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_session_with_preset_but_no_supervisors(page):
    """Session state from the version with a site filter: no supervisors, stale site keys."""
    at = signed_in(new_app())
    old = dict(preset="Last 30 days", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
               teams=["Echo"], languages=["Spanish"], sites=["North"], _w_sites=["North"])
    for key, value in old.items():
        at.session_state[key] = value
    at.run()
    if page in FILTER_PAGES:
        at.switch_page(page).run()
    assert not at.exception, at.exception
    assert not at.error
    if page in FILTER_PAGES:   # the Overview has no Filters menu, so it leaves the filter keys alone
        assert "sites" not in at.session_state and "_w_sites" not in at.session_state
        assert at.session_state["teams"] == ["Echo"]
        assert len(at.session_state["supervisors"]) > 1
        assert "Teams: Echo · Supervisors: all · Languages: Spanish" in filter_line(at)


def test_stale_metrics_module_is_reloaded():
    """A redeploy without a restart keeps the old ui and src.metrics loaded; both are reloaded."""
    run_page(None)
    import ui
    ui.VERSION = "old"
    del ui.metrics.agent_time_saved
    del ui.overview_filters
    at = run_page(None)
    assert not at.exception, at.exception
    assert hasattr(ui.metrics, "agent_time_saved") and hasattr(ui, "overview_filters")


# --- Filters menu and shared chart template ------------------------------------------------

def filters_label(at):
    return [p.proto.popover.label for p in at.get("popover") if p.proto.popover.label.startswith("Filters")]


def test_filters_menu_summary_and_count():
    at = run_page(LANGUAGES)
    assert filters_label(at) == ["Filters"]
    assert any(m.value == "Apr 1 – Sep 30, 2026 · All teams · All supervisors · All languages"
               for m in at.markdown)
    at.multiselect(key="_w_teams").set_value(["Echo"]).run()
    at.selectbox(key="_w_preset").set_value("Last 30 days").run()
    assert filters_label(at) == ["Filters (2)"]
    assert any(m.value == "Sep 1 – Sep 30, 2026 · Echo · All supervisors · All languages"
               for m in at.markdown)
    at.button(key="reset_filters").click().run()
    assert filters_label(at) == ["Filters"]


def test_every_chart_uses_the_bold_template():
    import plotly.io as pio
    at = run_page(None)
    for chart in at.get("plotly_chart"):
        layout = pio.from_json(chart.proto.spec).layout
        assert layout.template.layout.font.weight == "bold"
        assert layout.template.layout.hoverlabel.font.weight == "bold"
        assert layout.template.data.bar[0].textfont.weight == "bold"


def test_gradient_colors():
    import ui
    assert ui.gradient_colors([0.4, 0.7, None]) == ["#7FD1C7", "#3730A3", "#CBD5E1"]
    assert ui.label_color("#3730A3") == "#FFFFFF" and ui.label_color("#7FD1C7") == "#1D3557"


# --- Executive Overview: date picker, handle time, agent time saved, menus ----------------

def overview_markdown(at, text):
    return [m.value for m in at.markdown if text in m.value]


def test_overview_has_date_picker_not_filters_menu():
    at = run_page(None)
    assert not [p for p in at.get("popover") if p.proto.popover.label.startswith("Filters")]
    picker = at.date_input(key="_w_ov_dates")
    assert picker.value == (date(2026, 4, 1), date(2026, 9, 30))
    assert len(at.date_input) == 1


def test_overview_ignores_team_and_language_filters():
    """Other pages' filters don't narrow the Overview: it always covers everything."""
    at = run_page(None, teams=["Echo"], supervisors=["Cynthia Reyes"], languages=["Mandarin"])
    assert not at.exception, at.exception
    assert overview_markdown(at, "eligible calls adopted the tool")[0] == (
        "**8,114** of **12,836** eligible calls adopted the tool")


def test_overview_handle_time_card_full_range():
    import plotly.io as pio
    at = run_page(None)
    assert overview_markdown(at, "The tool saves") == [
        "<p class='aht-headline'>The tool saves 3m 43s per call vs the interpreter</p>"]
    fig = pio.from_json(at.get("plotly_chart")[2].proto.spec)
    bar = fig.data[0]
    assert list(bar.x) == ["Native speaker", "Translation tool", "Interpreter"]
    assert list(bar.text) == ["7:29", "9:15", "12:58"]
    assert list(bar.marker.color) == ["#1D3557", "#0F9D8A", "#F4A261"]
    assert "Calls: %{customdata[0]:,}" in bar.hovertemplate and "AHT: %{customdata[1]}" in bar.hovertemplate
    assert fig.layout.template.layout.font.weight == "bold"


def test_overview_fte_card_full_range_and_september():
    import plotly.io as pio
    at = run_page(None)
    assert overview_markdown(at, "FTE saved") == ["<div class='big-number'>0.48 <span>FTE saved</span></div>"]
    assert overview_markdown(at, "hours of agent time saved") == [
        "**501** hours of agent time saved on **8,114** tool calls"]
    sub = [h for h in at.subheader if h.value == "Agent Time Saved (FTE)"][0]
    assert "40 hours x weeks" in sub.help and "per-language" in sub.help
    fig = pio.from_json(at.get("plotly_chart")[3].proto.spec)
    assert list(fig.data[0].x) == ["Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"]
    assert fig.data[0].y[0] == 0   # before rollout: no tool calls
    at.date_input(key="_w_ov_dates").set_value((date(2026, 9, 1), date(2026, 9, 30))).run()
    assert not at.exception, at.exception
    assert overview_markdown(at, "FTE saved") == ["<div class='big-number'>0.84 <span>FTE saved</span></div>"]
    assert overview_markdown(at, "hours of agent time saved")[0].startswith("**143** hours")
    assert (at.session_state["ov_start"], at.session_state["ov_end"]) == (date(2026, 9, 1),
                                                                          date(2026, 9, 30))


def test_overview_dates_survive_page_switch():
    """The picked range is kept in ov_start / ov_end and re-seeds the picker when its
    widget state was dropped (as after visiting another page)."""
    at = run_page(None)
    at.date_input(key="_w_ov_dates").set_value((date(2026, 9, 1), date(2026, 9, 30))).run()
    at.switch_page(AGENTS).run()
    assert not at.exception, at.exception
    assert (at.session_state["ov_start"], at.session_state["ov_end"]) == (date(2026, 9, 1),
                                                                          date(2026, 9, 30))
    at = signed_in(new_app())   # a fresh run: no widget state yet
    at.session_state["ov_start"], at.session_state["ov_end"] = date(2026, 8, 1), date(2026, 8, 31)
    at.run()
    assert at.date_input(key="_w_ov_dates").value == (date(2026, 8, 1), date(2026, 8, 31))


def test_admin_menu_holds_account_and_user_management():
    at = run_page(None)
    assert [p.proto.popover.label for p in at.get("popover")] == ["User management"]
    assert overview_markdown(at, "Signed in as") == ["Signed in as **Test Admin** (admin)"]
    labels = [b.label for b in at.button]
    for label in ["Change password", "Sign out", "Approve requests (0)", "Manage users"]:
        assert label in labels
    at.button(key="manage_users_button").click().run()
    assert not at.exception, at.exception
    assert any(t.value == "User management" for t in at.title)


def test_overview_fees_saved_card():
    import plotly.io as pio
    at = run_page(None)
    assert overview_markdown(at, " <span>saved</span>") == [
        "<div class='big-number'>$134,476 <span>saved</span></div>"]
    assert overview_markdown(at, "per interpreter call") == [
        "on **8,114** tool calls at about **$16.57** per interpreter call"]
    sub = [h for h in at.subheader if h.value == "Interpreter Fees Saved"][0]
    assert "$1.75 per minute" in sub.help and "average interpreter cost" in sub.help
    fig = pio.from_json(at.get("plotly_chart")[4].proto.spec)
    assert fig.data[0].marker.color == "#0F9D8A" and fig.data[0].texttemplate == "$%{y:,.0f}"
    assert sum(fig.data[0].y) == pytest.approx(134475.82, abs=0.01)


def test_overview_interpreter_spend_card():
    import plotly.io as pio
    at = run_page(None)
    figures = overview_markdown(at, "spend-figures")[0]
    for text in ["<b>$184,014</b>total interpreter spend",
                 "<b>$78,640</b>spend where the tool was available",
                 "<b>105,151</b>interpreter minutes"]:
        assert text in figures
    fig = pio.from_json(at.get("plotly_chart")[5].proto.spec)
    assert fig.layout.barmode == "stack"
    assert [t.name for t in fig.data] == ["Tool not yet enabled", "Tool was available"]
    assert fig.layout.yaxis.tickprefix == "$"
    at.radio(key="ov_spend_measure").set_value("Minutes").run()
    assert not at.exception, at.exception
    fig = pio.from_json(at.get("plotly_chart")[5].proto.spec)
    assert fig.layout.yaxis.title.text == "Interpreter minutes"
    assert sum(fig.data[0].y) + sum(fig.data[1].y) == 105151


def test_axis_text_is_bold_black_on_every_page():
    import plotly.io as pio
    for page in PAGES:
        at = run_page(page)
        charts = at.get("plotly_chart")
        assert charts, page
        for chart in charts:
            layout = pio.from_json(chart.proto.spec).layout
            t = layout.template.layout
            for axis in (t.xaxis, t.yaxis):
                assert axis.tickfont.weight == "bold" and axis.tickfont.color == "#000000", page
                assert axis.title.font.weight == "bold" and axis.title.font.color == "#000000", page
            # Set on the figure too, since Streamlit's chart theme recolors template-only text.
            for name in [k for k in layout.to_plotly_json() if k.startswith(("xaxis", "yaxis"))]:
                axis = layout[name]
                assert axis.tickfont.color == "#000000" and axis.tickfont.weight == "bold", (page, name)
                assert axis.title.font.color == "#000000", (page, name)


# --- Agents & Teams: date range, Team and Supervisor dropdowns, adopters --------------------

def headline(at):
    return next(m.value for m in at.markdown if "ag-headline" in m.value)


def selection(at):
    return next(m.value for m in at.markdown if "ag-selection" in m.value)


def test_agents_page_sections_and_default_selection():
    at = run_page(AGENTS)
    assert not at.exception, at.exception
    assert [h.value for h in at.subheader] == ["Adoption by Language", "Agents: High and Low Adopters"]
    assert "All teams · All supervisors · Apr 1 – Sep 30, 2026" in selection(at)
    assert not [p for p in at.get("popover") if p.proto.popover.label.startswith("Filters")]
    assert at.selectbox(key="_w_ag_team").options[0] == "All"
    assert at.selectbox(key="_w_ag_supervisor").options[0] == "All"
    assert "All teams: 63.2% adoption on 12,836 eligible calls" in headline(at)   # = Overview


@pytest.mark.parametrize("team,pct", [("Atlas", "74.2%"), ("Beacon", "75.0%"), ("Cascade", "33.8%"),
                                      ("Delta", "74.7%"), ("Echo", "39.5%"), ("Summit", "66.3%")])
def test_agents_team_adoption_full_range(team, pct):
    at = run_page(AGENTS)
    at.selectbox(key="_w_ag_team").set_value(team).run()
    assert not at.exception, at.exception
    assert f"{team}: {pct} adoption on" in headline(at)


def test_agents_team_and_supervisor_follow_each_other():
    at = run_page(AGENTS)
    at.selectbox(key="_w_ag_team").set_value("Cascade").run()
    assert at.selectbox(key="_w_ag_supervisor").value == "Daniel Rose"
    assert "Cascade · Daniel Rose · Apr 1 – Sep 30, 2026" in selection(at)
    at.selectbox(key="_w_ag_supervisor").set_value("Rachel Young").run()
    assert at.selectbox(key="_w_ag_team").value == "Atlas"
    at.selectbox(key="_w_ag_supervisor").set_value("All").run()
    assert (at.selectbox(key="_w_ag_team").value, at.selectbox(key="_w_ag_supervisor").value) == ("All", "All")


def test_agents_language_chart_has_all_teams_marker():
    import plotly.io as pio
    at = run_page(AGENTS)
    at.selectbox(key="_w_ag_team").set_value("Cascade").run()
    fig = pio.from_json(at.get("plotly_chart")[0].proto.spec)
    bars, marker = fig.data
    assert list(bars.y) == ["Spanish", "Portuguese", "Mandarin", "Vietnamese"]
    assert list(bars.marker.color) == ["#2A9D8F", "#457B9D", "#E9C46A", "#9B5DE5"]
    assert marker.marker.symbol == "line-ns" and marker.name == "All teams"
    assert [round(x, 3) for x in marker.x] == [0.661, 0.687, 0.538, 0.529]   # all-teams, per language


def test_agents_high_and_low_adopters():
    at = run_page(AGENTS)
    assert any(c.value == "Agents with fewer than 20 eligible calls aren't ranked." for c in at.caption)
    high, low = (t.value for t in at.dataframe)
    assert len(high) == 10 and len(low) == 10
    assert list(high.columns) == ["Agent", "Team", "Eligible calls", "Tool calls",
                                  "Calls without the tool", "Adoption"]
    assert high["Adoption"].is_monotonic_decreasing and low["Adoption"].is_monotonic_increasing
    assert (high["Eligible calls"] >= 20).all() and (low["Eligible calls"] >= 20).all()
    at.slider(key="ag_min_calls").set_value(50).run()
    assert not at.exception, at.exception
    assert (at.dataframe[1].value["Eligible calls"] >= 50).all()
    labels = [d.proto.label for d in at.get("download_button")]
    assert "Download calls for coaching (CSV)" in labels
    assert any(lbl.startswith("Download ") and lbl.endswith("'s calls (CSV)") for lbl in labels)
    assert at.selectbox(key="ag_coach_agent").options[0] == at.dataframe[1].value["Agent"].iloc[0]


def test_palette_is_shared():
    import ui
    assert (ui.PATH_COLORS["translation_tool"], ui.PATH_COLORS["interpreter_line"],
            ui.PATH_COLORS["no_support"], ui.PATH_COLORS["native_exempt"]) == (
        "#0F9D8A", "#F4A261", "#E76F51", "#1D3557")
    assert ui.LANGUAGE_COLORS == {"Spanish": "#2A9D8F", "Portuguese": "#457B9D",
                                  "Mandarin": "#E9C46A", "Vietnamese": "#9B5DE5"}
    assert (ui.BORDER, ui.GRID) == ("#CBD5E1", "#E2E8F0")
