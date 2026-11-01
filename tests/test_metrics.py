"""Business rules and metric arithmetic on small hand-built datasets."""

import numpy as np
import pandas as pd
import pytest

import config as cfg
from src import metrics as m
from tests.fixtures import build_tables, call, interpreter, session


def enriched(con, call_id):
    return con.execute("select * from v_call_enriched where call_id = ?", [call_id]).df().iloc[0]


def linked(con, session_id):
    return con.execute("select * from v_session_linked where session_id = ?", [session_id]).df().iloc[0]


# --- Eligibility (native-speaker exemption) ---------------------------------

@pytest.fixture(scope="module")
def eligibility_con():
    return m.connect(tables=build_tables([
        call("NAT_ES", "NAT", "Spanish", "2026-06-10 09:00"),
        call("NAT_ZH", "NAT", "Mandarin", "2026-06-10 10:00"),
        call("NAT_PT", "NAT", "Portuguese", "2026-06-10 11:00"),
        call("BI_ES", "BI", "Spanish", "2026-06-10 09:00"),
        call("BI_PT", "BI", "Portuguese", "2026-06-10 10:00"),
        call("BI_VI", "BI", "Vietnamese", "2026-06-10 11:00"),
        call("FLU_ES", "FLU", "Spanish", "2026-06-10 09:00"),
        call("CON_ES", "CON", "Spanish", "2026-06-10 09:00"),
        call("MIS_ES", "MIS", "Spanish", "2026-06-10 09:00"),
        call("OFF_ES", "OFF", "Spanish", "2026-06-10 09:00"),
        call("NAT_EN", "NAT", "English", "2026-06-10 13:00"),
        call("FLU_EN", "FLU", "English", "2026-06-10 13:00"),
    ]))


def test_native_own_language_call_not_eligible(eligibility_con):
    row = enriched(eligibility_con, "NAT_ES")
    assert row.is_native_for_language and not row.eligible
    assert row.call_category == "native_exempt"
    assert pd.isna(row.handling_path) and pd.isna(row.expected_support)


@pytest.mark.parametrize("call_id", ["NAT_ZH", "NAT_PT"])
def test_native_agent_other_language_eligible(eligibility_con, call_id):
    """Native in Spanish only: Mandarin ('none' record) and Portuguese (no record) are eligible."""
    assert enriched(eligibility_con, call_id).eligible


def test_native_in_two_languages_exempt_for_both(eligibility_con):
    assert not enriched(eligibility_con, "BI_ES").eligible
    assert not enriched(eligibility_con, "BI_PT").eligible
    assert enriched(eligibility_con, "BI_VI").eligible


@pytest.mark.parametrize("call_id, level, has_record", [
    ("FLU_ES", "fluent", True),
    ("CON_ES", "conversational", True),
    ("MIS_ES", "none", False),   # no record at all -> treated as 'none'
    ("OFF_ES", "none", True),
])
def test_non_native_proficiency_is_eligible(eligibility_con, call_id, level, has_record):
    row = enriched(eligibility_con, call_id)
    assert row.eligible
    assert row.proficiency_level == level
    assert row.has_proficiency_record == has_record


@pytest.mark.parametrize("call_id", ["NAT_EN", "FLU_EN"])
def test_english_calls_never_eligible(eligibility_con, call_id):
    row = enriched(eligibility_con, call_id)
    assert not row.eligible and row.call_category == "english"


def test_agent_language_covers_every_agent_and_language(eligibility_con):
    df = eligibility_con.execute("select * from v_agent_language").df()
    assert len(df) == 6 * len(cfg.IN_SCOPE_LANGUAGES)
    assert set(df.loc[df.is_native, "agent_id"] + ":" + df.loc[df.is_native, "language"]) == {
        "NAT:Spanish", "BI:Spanish", "BI:Portuguese"}


# --- Expected support ----------------------------------------------------------

def test_expected_support_by_enablement_date():
    con = m.connect(tables=build_tables([
        call("BEFORE", "FLU", "Spanish", "2026-04-30 10:00"),   # FLU enabled 2026-05-01
        call("ON", "FLU", "Spanish", "2026-05-01 10:00"),
        call("AFTER", "FLU", "Spanish", "2026-05-02 10:00"),
        call("BLANK", "OFF", "Spanish", "2026-09-01 10:00"),    # tool_enabled_date blank
    ]))
    assert enriched(con, "BEFORE").expected_support == "interpreter_line"
    assert enriched(con, "ON").expected_support == "translation_tool"
    assert enriched(con, "AFTER").expected_support == "translation_tool"
    assert enriched(con, "BLANK").expected_support == "interpreter_line"
    assert enriched(con, "ON").days_since_enabled == 0
    assert pd.isna(enriched(con, "BEFORE").days_since_enabled)


# --- Handling path ---------------------------------------------------------------

def test_handling_path_priority():
    con = m.connect(
        tables=build_tables(
            [call("BOTH", "FLU", "Spanish", "2026-06-10 09:00"),
             call("INTERP", "FLU", "Spanish", "2026-06-10 10:00"),
             call("NONE", "FLU", "Spanish", "2026-06-10 11:00")],
            sessions=[session("S1", "FLU", "2026-06-10 09:01", call_id="BOTH")],
            interpreters=[interpreter("I1", "BOTH", 5), interpreter("I2", "INTERP", 7)]))
    assert enriched(con, "BOTH").handling_path == "translation_tool"
    assert enriched(con, "INTERP").handling_path == "interpreter_line"
    assert enriched(con, "NONE").handling_path == "no_support"
    assert enriched(con, "INTERP").interpreter_minutes == 7
    assert enriched(con, "INTERP").interpreter_cost_usd == pytest.approx(7 * 1.75)


# --- Session linking -------------------------------------------------------------

def test_session_linking_methods():
    con = m.connect(
        tables=build_tables(
            [call("C1", "FLU", "Spanish", "2026-06-10 09:00"),     # 09:00:00-09:09:00
             call("C2", "FLU", "Spanish", "2026-06-10 10:00")],
            sessions=[session("DIRECT", "FLU", "2026-06-10 10:01", call_id="C2"),
                      session("INSIDE", "FLU", "2026-06-10 09:03"),
                      session("OUTSIDE", "FLU", "2026-06-10 09:30"),
                      session("OTHER_AGENT", "CON", "2026-06-10 09:03")]))
    assert linked(con, "DIRECT").link_method == "call_id"
    inside = linked(con, "INSIDE")
    assert inside.link_method == "time_window" and inside.linked_call_id == "C1"
    assert linked(con, "OUTSIDE").link_method == "unlinked"
    assert pd.isna(linked(con, "OUTSIDE").linked_call_id)
    assert linked(con, "OTHER_AGENT").link_method == "unlinked"  # agent must match
    assert enriched(con, "C1").handling_path == "translation_tool"


def test_overlapping_candidates_pick_closest_start_and_flag_ambiguous():
    # C1 09:00:00-09:09:00, C2 09:09:30-09:18:30. With a 60s tolerance a session
    # at 09:09:10 is in neither call but near both; C2 starts closest.
    tables = build_tables(
        [call("C1", "FLU", "Spanish", "2026-06-10 09:00:00"),
         call("C2", "FLU", "Spanish", "2026-06-10 09:09:30")],
        sessions=[session("GAP", "FLU", "2026-06-10 09:09:10"),
                  session("IN_C1", "FLU", "2026-06-10 09:08:50")])
    con = m.connect(tables=tables, link_tolerance_sec=60)
    gap = linked(con, "GAP")
    assert gap.link_method == "time_window" and gap.linked_call_id == "C2"
    assert gap.is_ambiguous and gap.n_candidates == 2
    # Strict containment wins over a closer start within the tolerance.
    in_c1 = linked(con, "IN_C1")
    assert in_c1.linked_call_id == "C1" and not in_c1.is_ambiguous
    # Default tolerance (0) leaves the gap session unlinked.
    assert linked(m.connect(tables=tables), "GAP").link_method == "unlinked"
    dq = m.dq_session_links(con=con).set_index("link_method")
    assert dq.loc["time_window", "ambiguous_sessions"] == 1


# --- Exclusions from adoption -----------------------------------------------------

def test_session_before_enablement_excluded_from_adoption():
    con = m.connect(tables=build_tables(
        [call("EARLY", "FLU", "Spanish", "2026-04-20 10:00")],   # FLU enabled 2026-05-01
        sessions=[session("S_EARLY", "FLU", "2026-04-20 10:01", call_id="EARLY")]))
    assert linked(con, "S_EARLY").before_enablement
    row = enriched(con, "EARLY")
    assert row.handling_path == "no_support" and row.n_tool_sessions == 0
    k = m.kpi_summary(con=con).iloc[0]
    assert k.tool_calls == 0 and k.eligible_calls == 1
    assert m.dq_sessions_before_enablement(con=con)["session_id"].tolist() == ["S_EARLY"]


def test_native_optional_use_excluded_from_adoption():
    con = m.connect(tables=build_tables(
        [call("NAT_ES", "NAT", "Spanish", "2026-06-10 10:00"),
         call("FLU_ES", "FLU", "Spanish", "2026-06-10 10:00")],
        sessions=[session("S_NAT", "NAT", "2026-06-10 10:01", call_id="NAT_ES")]))
    assert linked(con, "S_NAT").is_optional_use
    assert enriched(con, "NAT_ES").is_optional_use
    k = m.kpi_summary(con=con).iloc[0]
    assert k.eligible_calls == 1 and k.enabled_tool_calls == 0 and k.tool_adoption == 0
    assert m.dq_session_links(con=con)["optional_use_sessions"].sum() == 1


# --- Rate arithmetic ----------------------------------------------------------------

RATE_CALLS = [
    call("R1", "FLU", "Spanish", "2026-06-10 10:00"),     # enabled, tool
    call("R2", "FLU", "Spanish", "2026-06-10 11:00"),     # enabled, tool
    call("R3", "CON", "Spanish", "2026-06-10 10:00"),     # enabled, tool
    call("R4", "MIS", "Vietnamese", "2026-06-10 10:00"),  # enabled, interpreter
    call("R5", "OFF", "Spanish", "2026-06-10 10:00"),     # not enabled, interpreter
    call("R6", "OFF", "Mandarin", "2026-06-10 11:00"),    # not enabled, no support
    call("R7", "NAT", "Spanish", "2026-06-10 10:00"),     # native, optional use
    call("R8", "FLU", "English", "2026-06-10 13:00"),     # English
]
RATE_SESSIONS = [session("SR1", "FLU", "2026-06-10 10:01", call_id="R1"),
                 session("SR2", "FLU", "2026-06-10 11:02"),   # null call_id, inside R2
                 session("SR3", "CON", "2026-06-10 10:01", call_id="R3"),
                 session("SR7", "NAT", "2026-06-10 10:01", call_id="R7")]
RATE_INTERP = [interpreter("IR4", "R4", 10), interpreter("IR5", "R5", 4)]


def test_adoption_compliance_supported_arithmetic():
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    k = m.kpi_summary(con=con).iloc[0]
    assert k.eligible_calls == 6
    assert (k.enabled_eligible_calls, k.enabled_tool_calls) == (4, 3)
    assert k.tool_adoption == pytest.approx(0.75)
    assert (k.not_enabled_eligible_calls, k.not_enabled_interpreter_calls) == (2, 1)
    assert k.interpreter_compliance == pytest.approx(0.5)
    assert k.supported_rate == pytest.approx(4 / 6)
    assert k.interpreter_spend_usd == pytest.approx(14 * 1.75)
    assert k.interpreter_spend_where_tool_available_usd == pytest.approx(10 * 1.75)

    mix = m.handling_path_mix(con=con).set_index(["expected_support", "handling_path"])["calls"]
    assert mix.to_dict() == {("translation_tool", "translation_tool"): 3,
                             ("translation_tool", "interpreter_line"): 1,
                             ("interpreter_line", "interpreter_line"): 1,
                             ("interpreter_line", "no_support"): 1}
    team = m.adoption_by(by="team", con=con).set_index("team")
    assert team.loc["T1", "tool_adoption"] == 1.0          # FLU 2 of 2
    assert team.loc["T2", "tool_adoption"] == pytest.approx(0.5)   # CON 1, MIS 0
    assert np.isnan(m.adoption_by(by="agent", con=con).set_index("agent_id")
                    .loc["OFF", "tool_adoption"])


def test_handling_path_trend_matches_mix():
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    trend = m.handling_path_trend(grain="week", con=con)
    assert set(trend["handling_path"]) == {"translation_tool", "interpreter_line", "no_support"}
    by_path = trend.groupby("handling_path")["calls"].sum().to_dict()
    mix = m.handling_path_mix(con=con).groupby("handling_path")["calls"].sum().to_dict()
    assert {k: v for k, v in by_path.items() if v} == mix
    assert trend.groupby("week_start")["share_of_period"].sum().tolist() == pytest.approx([1.0])


def test_low_adopters_is_leaderboard_reversed():
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    best = m.agent_leaderboard(min_enabled_calls=1, con=con)
    worst = m.low_adopters(min_enabled_calls=1, con=con)
    assert worst["tool_adoption"].is_monotonic_increasing
    assert set(best["agent_id"]) == set(worst["agent_id"])
    assert m.low_adopters(min_enabled_calls=99, con=con).empty


def test_team_rollout_dates_respect_team_and_supervisor():
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    assert len(m.team_rollout_dates(con=con)) == len(con.execute("from dim_team").df())
    assert m.team_rollout_dates(teams=["T1"], con=con)["team"].tolist() == ["T1"]
    assert m.team_rollout_dates(teams=["nobody"], con=con).empty
    assert m.team_rollout_dates(supervisors=["Sup Two"], con=con)["team"].tolist() == ["T2"]


def test_adoption_split_matches_tool_adoption():
    """Donut: tool-enabled eligible calls only; not-enabled calls (OFF, pre-rollout) excluded."""
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    split = m.adoption_split(con=con).set_index("slice")
    assert split["calls"].to_dict() == {"Adopted the tool": 3, "Did not adopt": 1}
    assert split.loc["Adopted the tool", "share"] == pytest.approx(
        m.kpi_summary(con=con).iloc[0].tool_adoption)
    empty = m.adoption_split(teams=["nobody"], con=con)
    assert empty["calls"].sum() == 0 and empty["share"].isna().all()


def test_not_adopted_trend_splits_tool_enabled_calls():
    """Tool-enabled eligible calls without the tool, split by path; not-enabled calls excluded."""
    con = m.connect(tables=build_tables(
        RATE_CALLS + [call("N1", "CON", "Spanish", "2026-06-11 10:00")],   # enabled, no support
        RATE_SESSIONS, RATE_INTERP))
    day = m.not_adopted_trend(grain="day", con=con).set_index("period_start")
    assert day["eligible_calls"].to_dict() == {pd.Timestamp("2026-06-10"): 4,
                                               pd.Timestamp("2026-06-11"): 1}
    assert day.loc["2026-06-10", ["interpreter_calls", "no_support_calls"]].tolist() == [1, 0]
    assert day.loc["2026-06-11", ["interpreter_calls", "no_support_calls"]].tolist() == [0, 1]
    assert day["not_adopted_share"].tolist() == pytest.approx([0.25, 1.0])
    week = m.not_adopted_trend(grain="week", con=con).iloc[0]
    split = m.adoption_split(con=con).set_index("slice")["calls"]
    assert week.not_adopted_calls == split["Did not adopt"] == 2
    assert week.not_adopted_share == pytest.approx(2 / 5)
    # A week starting before start_date is labeled with start_date.
    clipped = m.not_adopted_trend("2026-06-11", "2026-09-30", grain="week", con=con)
    assert clipped["period_start"].tolist() == [pd.Timestamp("2026-06-11")]


def test_not_adopted_grain_switches_at_31_days():
    assert m.not_adopted_grain("2026-09-01", "2026-10-01") == "day"     # 31 days
    assert m.not_adopted_grain("2026-09-01", "2026-10-02") == "week"    # 32 days
    assert m.not_adopted_grain(None, None) == "week"
    con = m.connect(tables=build_tables(RATE_CALLS, RATE_SESSIONS, RATE_INTERP))
    assert len(m.not_adopted_trend("2026-06-01", "2026-06-30", con=con)) == 1   # one day with calls


def test_cost_avoided_formula():
    pre = [  # April = before the first rollout (2026-05-01)
        call("P1", "FLU", "Spanish", "2026-04-10 09:00"),
        call("P2", "FLU", "Spanish", "2026-04-10 10:00"),
        call("P3", "FLU", "Spanish", "2026-04-10 11:00"),
        call("P4", "FLU", "Spanish", "2026-04-10 12:00"),
        call("P5", "MIS", "Mandarin", "2026-04-10 09:00"),
    ]
    post = [
        call("T1", "FLU", "Spanish", "2026-06-10 09:00"),
        call("T2", "FLU", "Spanish", "2026-06-10 10:00"),
        call("T3", "FLU", "Spanish", "2026-06-10 11:00"),
        call("T4", "MIS", "Mandarin", "2026-06-10 09:00"),
        call("NATC", "NAT", "Spanish", "2026-06-10 09:00"),
    ]
    sessions = [session(f"S{c}", a, f"2026-06-10 {h}:01", call_id=c)
                for c, a, h in [("T1", "FLU", "09"), ("T2", "FLU", "10"), ("T3", "FLU", "11"),
                                ("T4", "MIS", "09"), ("NATC", "NAT", "09")]]
    sessions.append(session("PRACTICE", "FLU", "2026-06-10 15:00"))       # unlinked
    sessions.append(session("EARLY", "FLU", "2026-04-10 12:01", call_id="P4"))  # before enablement
    interps = [interpreter("I1", "P1", 10), interpreter("I2", "P2", 6), interpreter("I3", "P5", 8)]
    con = m.connect(tables=build_tables(pre + post, sessions, interps))

    base = m.cost_avoided_by_language(con=con).set_index("language")
    # Spanish: share 2/4, avg 8 min -> 3 tool calls x 0.5 x 8 x 1.75 = 21.0
    assert base.loc["Spanish", "interpreter_share"] == pytest.approx(0.5)
    assert base.loc["Spanish", "avg_interpreter_minutes"] == pytest.approx(8)
    assert base.loc["Spanish", "tool_calls"] == 3
    assert base.loc["Spanish", "cost_avoided_usd"] == pytest.approx(21.0)
    # Mandarin: share 1/1, avg 8 min -> 1 x 1.0 x 8 x 1.75 = 14.0
    assert base.loc["Mandarin", "cost_avoided_usd"] == pytest.approx(14.0)
    assert m.kpi_summary(con=con).iloc[0].cost_avoided_usd == pytest.approx(35.0)
    # Filters change the tool calls counted, not the fixed baseline.
    es = m.kpi_summary(languages=["Spanish"], con=con).iloc[0]
    assert es.cost_avoided_usd == pytest.approx(21.0)


# --- Filters ----------------------------------------------------------------------------

FILTER_CALLS = RATE_CALLS + [
    call("F1", "FLU", "Spanish", "2026-05-12 09:00"),
    call("F2", "MIS", "Portuguese", "2026-05-12 10:00"),
    call("F3", "CON", "Spanish", "2026-04-15 09:00"),
    call("F4", "BI", "Portuguese", "2026-07-01 09:00"),
    call("F5", "OFF", "English", "2026-07-01 09:00", transferred=True, csat=3),
]
FILTER_SESSIONS = RATE_SESSIONS + [
    session("SF1", "FLU", "2026-05-12 09:01", call_id="F1"),
    session("SF3", "CON", "2026-04-15 09:01", call_id="F3", language="Spanish"),  # pre-enablement
    session("SPRAC", "MIS", "2026-07-01 15:00", language="Portuguese"),          # unlinked
]
FILTER_INTERP = RATE_INTERP + [interpreter("IF2", "F2", 6), interpreter("IF3", "F3", 9)]

# Every metric function with the extra arguments that pick a non-trivial shape.
FUNCTIONS = {
    "kpi_summary": {},
    "adoption_split": {},
    "not_adopted_trend": {"grain": "week"},
    "adoption_trend_week": {"grain": "week"},
    "adoption_trend_month_team": {"grain": "month", "by": "team", "fn": "adoption_trend"},
    "adoption_by_supervisor": {"by": "supervisor", "fn": "adoption_by"},
    "adoption_by_site": {"by": "site", "fn": "adoption_by"},
    "adoption_by_language": {"by": "language", "fn": "adoption_by"},
    "adoption_by_agent": {"by": "agent", "fn": "adoption_by"},
    "agent_leaderboard": {"min_enabled_calls": 0},
    "low_adopters": {"min_enabled_calls": 0},
    "handling_path_mix": {},
    "handling_path_trend": {"grain": "week"},
    "ramp_curve": {"bucket_days": 7},
    "ramp_curve_team": {"bucket_days": 7, "by": "team", "fn": "ramp_curve"},
    "routing_mix": {"grain": "day"},
    "language_summary": {},
    "operational_by_path": {"by_language": True},
    "interpreter_spend": {"grain": "day", "by_language": True},
    "cost_avoided": {"grain": "week", "by_language": True},
    "cost_avoided_by_language": {},
    "dq_session_links": {},
    "dq_sessions_before_enablement": {},
    "dq_agents_without_language_records": {},
    "dq_summary": {},
}
NON_ADDITIVE = {"agents", "days_since_enabled", "languages_missing", "pre_rollout_eligible_calls",
                "pre_rollout_interpreter_calls", "value"}
ROW_LISTS = {"dq_sessions_before_enablement"}   # functions returning one row per record
PARTITIONS = {
    "date": [{"end_date": "2026-05-31"}, {"start_date": "2026-06-01"}],
    "team": [{"teams": ["T1"]}, {"teams": ["T2"]}],
    "supervisor": [{"supervisors": ["Sup One"]}, {"supervisors": ["Sup Two"]}],
    "language": [{"languages": [lang]} for lang in ["English"] + cfg.IN_SCOPE_LANGUAGES],
}
# Agents in the fixtures are hired 2025-01-01, so a 2024 window holds nothing.
EXCLUDE = {"date": {"start_date": "2024-01-01", "end_date": "2024-12-31"}, "team": {"teams": ["nobody"]},
           "supervisor": {"supervisors": ["nobody"]}, "language": {"languages": ["Klingon"]}}


@pytest.fixture(scope="module")
def filter_con():
    return m.connect(tables=build_tables(FILTER_CALLS, FILTER_SESSIONS, FILTER_INTERP))


def run(name, con, **filters):
    args = dict(FUNCTIONS[name])
    fn = getattr(m, args.pop("fn", name.split("_week")[0]))
    return fn(**filters, **args, con=con)


def totals(df):
    """Sum of every additive count/money column, plus the row count."""
    cols = [c for c in df.select_dtypes("number").columns
            if c not in NON_ADDITIVE and (pd.api.types.is_integer_dtype(df[c]) or c in m.MONEY)]
    return pd.Series({"rows": len(df), **{c: df[c].sum() for c in cols}})


@pytest.mark.parametrize("dim", list(EXCLUDE))
@pytest.mark.parametrize("name", list(FUNCTIONS))
def test_filter_excluding_everything_gives_nothing(filter_con, name, dim):
    t = totals(run(name, filter_con, **EXCLUDE[dim]))
    if name in ("kpi_summary", "adoption_split", "dq_summary"):   # fixed rows
        t = t.drop("rows")
    if name == "dq_summary":
        assert (run(name, filter_con, **EXCLUDE[dim])["value"] == 0).all()
    assert (t == 0).all(), t[t != 0]


@pytest.mark.parametrize("dim", list(PARTITIONS))
@pytest.mark.parametrize("name", [n for n in FUNCTIONS
                                  if n not in ("dq_summary", "dq_agents_without_language_records")])
def test_filter_partitions_add_up(filter_con, name, dim):
    """Counts filtered to each part of a partition add up to the unfiltered counts."""
    def part_totals(**f):
        t = totals(run(name, filter_con, **f))
        return t if name in ROW_LISTS else t.drop("rows")   # rows are groups, not counts

    whole = part_totals()
    parts = sum(part_totals(**p) for p in PARTITIONS[dim])
    assert whole.sum() > 0
    pd.testing.assert_series_equal(parts.astype(float).sort_index(),
                                   whole.astype(float).sort_index(), check_names=False)


def test_filters_known_counts(filter_con):
    count = lambda **f: m.kpi_summary(**f, con=filter_con).iloc[0].eligible_calls  # noqa: E731
    assert count() == 9           # R1-R6 + F1, F2, F3 (F4 native, F5 English)
    assert count(teams=["T1"]) == 3                 # R1, R2, F1
    assert count(supervisors=["Sup Two"]) == 6
    assert count(languages=["Portuguese"]) == 1     # F2
    assert count(start_date="2026-05-01", end_date="2026-05-31") == 2
    assert count(teams=[]) == 0
    missing = m.dq_agents_without_language_records(con=filter_con)
    assert missing["agent_id"].tolist() == ["MIS"]
    assert m.dq_agents_without_language_records(teams=["T1"], con=filter_con).empty
    # Agents missing records for the selected language only.
    assert set(m.dq_agents_without_language_records(languages=["Vietnamese"], con=filter_con)
               ["agent_id"]) == {"NAT", "BI", "FLU", "CON", "MIS", "OFF"}


def test_orphan_interpreter_rows_reported(filter_con):
    con = m.connect(tables=build_tables(
        FILTER_CALLS, FILTER_SESSIONS, FILTER_INTERP + [interpreter("IGHOST", "NO_SUCH_CALL", 3)]))
    assert m.dq_orphan_interpreter_rows(con=con)["interpreter_call_id"].tolist() == ["IGHOST"]
    assert m.dq_orphan_interpreter_rows(con=filter_con).empty


# --- Different routing ---------------------------------------------------------------------

def test_views_unchanged_under_different_routing(monkeypatch):
    """Generate a short dataset with a different routing setting (calls wait
    up to 2 minutes for a native) and check the views still hold together."""
    from datetime import date
    from data_gen import generate as gen

    results = {}
    for wait in (0, 120):
        monkeypatch.setattr(cfg, "END_DATE", date(2026, 6, 15))
        monkeypatch.setattr(cfg, "NATIVE_WAIT_SEC", wait)
        tables, _ = gen.generate()
        con = m.connect(tables=tables)
        k = m.kpi_summary(con=con).iloc[0]
        routing = m.routing_mix(con=con)
        assert routing["overflow_calls"].sum() == k.eligible_calls
        assert m.handling_path_mix(con=con)["calls"].sum() == k.eligible_calls
        assert k.supported_calls <= k.eligible_calls
        for name in FUNCTIONS:
            run(name, con)
        results[wait] = routing["overflow_rate"].mean()
    assert results[120] < results[0]   # waiting for natives reduces overflow
