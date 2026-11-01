"""Smoke tests: every dashboard page renders without errors under default and narrowed filters."""

from datetime import date

import pytest

from tests.conftest import new_app, signed_in

PAGES = [None, "views/1_Agents_and_Teams.py", "views/2_Languages.py",
         "views/3_Operational_Impact.py", "views/4_Cost.py", "views/5_Data_Quality.py"]


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
    return next(m.value for m in at.markdown if "2026" in m.value)


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
    at = run_page(None, preset="Custom", start_date=date(2026, 9, 30), end_date=date(2026, 9, 1))
    assert not at.exception
    assert any("Start date is after end date" in w.value for w in at.warning)


def test_empty_selection_shows_friendly_message():
    at = run_page(None, teams=[])
    assert not at.exception
    assert any("Select at least one team" in w.value for w in at.warning)


def test_preset_sets_dates():
    at = signed_in(new_app())
    at.run()
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
    assert not [m for m in at.markdown if "2026" in m.value]   # no date range line
    assert not [c for c in at.caption if c.value.startswith("Teams:")]
    assert [h.value for h in at.subheader] == ["Adoption Percentage", "Trends"]
    line = [m for m in at.markdown if "eligible calls adopted the tool" in m.value][0]
    assert line.value == "**8,114** of **14,844** eligible calls adopted the tool"
    assert line.help.startswith("Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese")
    assert not [c for c in at.caption if "Contact center calls" in c.value]


def test_overview_repeat_non_users():
    at = run_page(None)
    sub = [h for h in at.subheader if h.value == "Trends"][0]
    assert sub.help.startswith("Agents whose tool was enabled but who handled eligible calls")
    slider = at.slider(key="min_missed")
    assert (slider.value, slider.min, slider.max) == (3, 1, 93)   # max = most missed by one agent
    line = [m for m in at.markdown if "missed calls (at least" in m.value][0]
    assert line.value == "**143** agents with **6,728** missed calls (at least 3 each)"
    assert any(c.value == "Showing 10 of 143 agents; the CSV includes all." for c in at.caption)
    at.slider(key="min_missed").set_value(1).run()
    line = [m for m in at.markdown if "missed calls (at least" in m.value][0]
    assert line.value == "**145** agents with **6,730** missed calls (at least 1 each)"
    at.slider(key="min_missed").set_value(90).run()
    assert not at.exception
    line = [m for m in at.markdown if "missed calls (at least" in m.value][0]
    assert line.value == "**2** agents with **184** missed calls (at least 90 each)"
    assert not [c for c in at.caption if c.value.startswith("Showing")]


def test_overview_slider_clamps_to_new_max():
    """Narrowing the filters lowers the slider's max and pulls a higher value down to it."""
    at = run_page(None)
    at.slider(key="min_missed").set_value(90).run()
    at.session_state["teams"] = ["Echo"]
    at.session_state["languages"] = ["Mandarin"]
    at.run()
    assert not at.exception, at.exception
    slider = at.slider(key="min_missed")
    assert slider.max < 90 and slider.value == slider.max


def test_overview_trends_chart_single_series():
    import plotly.io as pio
    at = run_page(None)
    fig = pio.from_json(at.get("plotly_chart")[1].proto.spec)
    assert [t.type for t in fig.data] == ["bar"]
    assert fig.data[0].marker.color == "#F4A261" and not fig.layout.showlegend
    assert list(fig.data[0].x[:3]) == sorted(fig.data[0].x, reverse=True)[:3]


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
    at = run_page(None)
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
    assert "sites" not in at.session_state and "_w_sites" not in at.session_state
    assert at.session_state["teams"] == ["Echo"]
    assert len(at.session_state["supervisors"]) > 1
    if page:
        assert "Teams: Echo · Supervisors: all · Languages: Spanish" in filter_line(at)


def test_stale_metrics_module_is_reloaded():
    """A redeploy without a restart keeps the old ui and src.metrics loaded; both are reloaded."""
    run_page(None)
    import ui
    ui.VERSION = "old"
    del ui.metrics.repeat_non_users
    del ui.render_filter_bar
    at = run_page(None)
    assert not at.exception, at.exception
    assert hasattr(ui.metrics, "repeat_non_users") and hasattr(ui, "render_filter_bar")
