"""Smoke tests: every dashboard page renders without errors under default and narrowed filters."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
PAGES = [None, "views/1_Agents_and_Teams.py", "views/2_Languages.py",
         "views/3_Operational_Impact.py", "views/4_Cost.py", "views/5_Data_Quality.py"]


def run_page(page, **state):
    at = AppTest.from_file(ENTRY, default_timeout=120)
    at.run()
    for key, value in state.items():
        at.session_state[key] = value
    if page:
        at.switch_page(page)
    at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_default_filters(page):
    at = run_page(page)
    assert not at.exception, at.exception
    assert not at.error
    assert "Apr 01, 2026 – Sep 30, 2026" in at.markdown[0].value


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_narrow_filters(page):
    at = run_page(page, preset="Last 30 days", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
                  teams=["Echo"], languages=["Mandarin"])
    assert not at.exception, at.exception
    assert not at.error
    assert "Sep 01, 2026 – Sep 30, 2026" in at.markdown[0].value
    assert "Teams: Echo" in at.caption[0].value


def test_start_after_end_shows_friendly_message():
    at = run_page(None, preset="Custom", start_date=date(2026, 9, 30), end_date=date(2026, 9, 1))
    assert not at.exception
    assert any("Start date is after end date" in w.value for w in at.warning)


def test_empty_selection_shows_friendly_message():
    at = run_page(None, teams=[])
    assert not at.exception
    assert any("Select at least one team" in w.value for w in at.warning)


def test_preset_sets_dates():
    at = AppTest.from_file(ENTRY, default_timeout=120)
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
        assert "Teams: Echo · Supervisors: Cynthia Reyes · Languages: Mandarin" in at.caption[0].value


def test_overview_adoption_card():
    at = run_page(None)
    assert not at.exception
    assert [h.value for h in at.subheader] == ["Adoption Percentage", "Agents Repeatedly Not Using the Tool"]
    line = [m for m in at.markdown if "eligible calls adopted the tool" in m.value][0]
    assert line.value == "**8,114** of **14,844** eligible calls adopted the tool"
    assert line.help.startswith("Eligible calls: Spanish, Portuguese, Mandarin or Vietnamese")
    assert not [c for c in at.caption if "Contact center calls" in c.value]


def test_overview_repeat_non_users():
    at = run_page(None)
    sub = [h for h in at.subheader if h.value == "Agents Repeatedly Not Using the Tool"][0]
    assert sub.help.startswith("Agents whose tool was enabled but who handled eligible calls")
    assert at.number_input(key="min_missed").value == 3
    line = [m for m in at.markdown if "missed calls (at least" in m.value][0]
    assert line.value == "**143** agents with **6,728** missed calls (at least 3 each)"
    assert any(c.value == "Showing 15 of 143 agents; the CSV includes all." for c in at.caption)
    at.number_input(key="min_missed").set_value(90).run()
    assert not at.exception
    line = [m for m in at.markdown if "missed calls (at least" in m.value][0]
    assert line.value == "**2** agents with **184** missed calls (at least 90 each)"
    assert not [c for c in at.caption if c.value.startswith("Showing")]
    at.number_input(key="min_missed").set_value(500).run()
    assert any("No agents have 500 or more missed calls" in i.value for i in at.info)


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
    at.button[-1].click().run()   # Reset
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_session_with_preset_but_no_supervisors(page):
    """Session state from the version with a site filter: no supervisors, stale site keys."""
    at = AppTest.from_file(ENTRY, default_timeout=120)
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
    assert "Teams: Echo · Supervisors: all · Languages: Spanish" in at.caption[0].value


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
