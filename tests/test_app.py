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
