"""Checks on the committed synthetic data in data/raw/."""

import io
from pathlib import Path

import pandas as pd
import pytest

import config as cfg
from data_gen import checks
from data_gen.generate import generate

RAW = Path(__file__).resolve().parents[1] / cfg.RAW_DATA_DIR


@pytest.fixture(scope="module")
def tables():
    return checks.load_tables(RAW)


@pytest.mark.parametrize("check", checks.ALL_CHECKS, ids=lambda f: f.__name__)
def test_data_check(tables, check):
    ok, detail = check(tables)
    assert ok, detail


def test_routing_reason_matches_native_exemption(tables):
    """In-scope calls are 'native' exactly when the agent is native in the caller's language."""
    natives = tables["agent_language_proficiency"].query("proficiency_level == 'native'")
    native_set = set(zip(natives["agent_id"], natives["language"]))
    c = tables["fact_call"]
    in_scope = c["caller_language"].isin(cfg.IN_SCOPE_LANGUAGES)
    is_native = pd.Series([(a, lg) in native_set for a, lg in zip(c["agent_id"], c["caller_language"])])
    assert c.loc[~in_scope, "routing_reason"].isna().all()
    assert ((c.loc[in_scope, "routing_reason"] == "native") == is_native[in_scope]).all()


def test_not_enabled_agents_have_no_call_sessions(tables):
    """Sessions linked to a call only happen on or after the agent's tool_enabled_date."""
    s = tables["fact_translation_session"].dropna(subset=["call_id"])
    enabled = pd.to_datetime(s["agent_id"].map(
        tables["dim_agent"].set_index("agent_id")["tool_enabled_date"]))
    assert (s["session_start_ts"].dt.normalize() >= enabled).all()


def test_interpreter_calls_have_connect_hold(tables):
    i = tables["fact_interpreter_usage"]
    hold = i["call_id"].map(tables["fact_call"].set_index("call_id")["hold_sec"])
    assert (hold >= cfg.INTERPRETER_CONNECT_HOLD_SEC).all()


def test_dim_team_matches_config(tables):
    t = tables["dim_team"].set_index("team")
    assert set(t.index) == set(cfg.TEAMS)
    assert (pd.to_datetime(t["rollout_date"]) == pd.to_datetime(
        t.index.map(cfg.TEAM_ROLLOUT_DATES))).all()


def test_reproducible(tables):
    """Re-running the generator reproduces the committed files exactly."""
    fresh, _ = generate()
    for name, df in fresh.items():
        on_disk = tables[name]
        pd.testing.assert_frame_equal(
            pd.read_parquet(_roundtrip(df)), on_disk, check_dtype=False, obj=name)


def _roundtrip(df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    return buf
