"""Smoke tests: every dashboard page renders without errors under default and narrowed filters."""

from datetime import date

import pytest

from tests.conftest import new_app, signed_in

PAGES = [None, "views/1_Agents_and_Teams.py", "views/2_Languages.py",
         "views/3_Operational_Impact.py", "views/4_Cost.py", "views/5_Data_Quality.py"]
AGENTS = PAGES[1]


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
    if page:   # the Overview leaves the filter summary to the filter bar
        assert "Apr 01, 2026 – Sep 30, 2026" in date_line(at)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_narrow_filters(page):
    at = run_page(page, preset="Last 30 days", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
                  teams=["Echo"], languages=["Mandarin"])
    assert not at.exception, at.exception
    assert not at.error
    if page:
        assert "Sep 01, 2026 – Sep 30, 2026" in date_line(at)
        assert "Teams: Echo" in filter_line(at)


def test_start_after_end_shows_friendly_message():
    at = run_page(AGENTS, preset="Custom", start_date=date(2026, 9, 30), end_date=date(2026, 9, 1))
    assert not at.exception
    assert any("Start date is after end date" in w.value for w in at.warning)


def test_empty_selection_shows_friendly_message():
    at = run_page(AGENTS, teams=[])
    assert not at.exception
    assert any("Select at least one team" in w.value for w in at.warning)


def test_preset_sets_dates():
    at = run_page(AGENTS)
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
        assert "Teams: Echo · Supervisors: Cynthia Reyes · Languages: Mandarin" in filter_line(at)


def test_overview_adoption_card():
    at = run_page(None)
    assert not at.exception
    assert at.title[0].value == "Translation Tool Adoption"
    assert not [m for m in at.markdown if m.value.startswith("**Apr")]   # no date range line
    assert not [c for c in at.caption if c.value.startswith("Teams:")]
    assert [h.value for h in at.subheader] == ["Adoption Percentage", "Adoption by Month",
                                               "Calls vs Tool Use by Language",
                                               "Handle Time by Support Type", "Agent Time Saved (FTE)"]
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
    at = run_page(AGENTS)
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
    if page:
        at.switch_page(page).run()
    assert not at.exception, at.exception
    assert not at.error
    if page:   # the Overview has no Filters menu, so it leaves the filter keys alone
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
    at = run_page(AGENTS)
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
    assert overview_markdown(at, "FTE saved") == ["<div class='fte-big'>0.48 <span>FTE saved</span></div>"]
    assert overview_markdown(at, "hours of agent time saved") == [
        "**501** hours of agent time saved on **8,114** tool calls"]
    sub = [h for h in at.subheader if h.value == "Agent Time Saved (FTE)"][0]
    assert "40 hours x weeks" in sub.help and "per-language" in sub.help
    fig = pio.from_json(at.get("plotly_chart")[3].proto.spec)
    assert list(fig.data[0].x) == ["Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"]
    assert fig.data[0].y[0] == 0   # before rollout: no tool calls
    at.date_input(key="_w_ov_dates").set_value((date(2026, 9, 1), date(2026, 9, 30))).run()
    assert not at.exception, at.exception
    assert overview_markdown(at, "FTE saved") == ["<div class='fte-big'>0.84 <span>FTE saved</span></div>"]
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
