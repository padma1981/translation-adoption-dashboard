"""Metric layer: loads the DuckDB views in sql/ and returns chart-ready DataFrames.

Every metric function takes the same filters:
    start_date, end_date  inclusive dates (None = no bound)
    teams, sites          lists of names (None = all; [] = nothing)
    languages             caller languages, or source language for sessions
plus an optional `con` (defaults to the shared connection over data/raw/).
Rates are ratios of summed counts, so they stay correct at any grain.
"""

from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config as cfg  # noqa: E402

SQL_DIR = ROOT / "sql"
RAW_TABLES = ["dim_agent", "dim_team", "agent_language_proficiency", "fact_call",
              "fact_translation_session", "fact_interpreter_usage"]
GRAINS = {"day": "day", "week": "week_start", "month": "month_start"}
DIMENSIONS = {
    "team": ["team"],
    "supervisor": ["supervisor", "team"],
    "site": ["site"],
    "language": ["language"],
    "agent": ["agent_id", "agent_name", "team", "supervisor", "site"],
}
ADOPTION_COUNTS = ["eligible_calls", "enabled_eligible_calls", "enabled_tool_calls",
                   "not_enabled_eligible_calls", "not_enabled_interpreter_calls",
                   "supported_calls", "tool_calls", "interpreter_calls", "no_support_calls"]
MONEY = {"interpreter_spend_usd", "cost_avoided_usd"}

_default_con = None


# --- Connection ------------------------------------------------------------

def connect(raw_dir=None, tables=None, link_tolerance_sec=None) -> duckdb.DuckDBPyConnection:
    """New in-memory DuckDB connection with all views loaded.

    Reads Parquet from raw_dir (default config.RAW_DATA_DIR), or uses the
    DataFrames in `tables` (name -> DataFrame) instead, e.g. for tests.
    """
    con = duckdb.connect()
    if tables is not None:
        for name in RAW_TABLES:
            con.register(name, tables[name])
    else:
        raw = Path(raw_dir) if raw_dir else ROOT / cfg.RAW_DATA_DIR
        for name in RAW_TABLES:
            path = (raw / f"{name}.parquet").as_posix()
            con.execute(f"create view {name} as select * from read_parquet('{path}')")

    tol = cfg.LINK_TOLERANCE_SEC if link_tolerance_sec is None else link_tolerance_sec
    params = {
        ":in_scope_languages": ", ".join(f"'{lang}'" for lang in cfg.IN_SCOPE_LANGUAGES),
        ":link_tolerance_sec": str(int(tol)),
        ":interpreter_cost_per_min": str(float(cfg.INTERPRETER_COST_PER_MIN)),
    }
    for path in sorted(SQL_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for key, value in params.items():
            sql = sql.replace(key, value)
        con.execute(sql)
    return con


def get_connection() -> duckdb.DuckDBPyConnection:
    """Shared connection over data/raw/, created once."""
    global _default_con
    if _default_con is None:
        _default_con = connect()
    return _default_con


def _where(start_date, end_date, teams, sites, languages, date_col="day", lang_col="language"):
    """SQL where clause and parameters for the standard filters."""
    clauses, params = ["true"], []
    if start_date is not None:
        clauses.append(f"{date_col} >= ?")
        params.append(pd.Timestamp(start_date).date())
    if end_date is not None:
        clauses.append(f"{date_col} <= ?")
        params.append(pd.Timestamp(end_date).date())
    for col, values in (("team", teams), ("site", sites), (lang_col, languages)):
        if values is not None:
            clauses.append(f"list_contains(?::varchar[], {col})")
            params.append(list(values))
    return " and ".join(clauses), params


def _sum_by(view, keys, measures, filters, con, order=None):
    """Sum measures from a view grouped by keys, after applying filters."""
    where, params = _where(*filters)
    sums = [f"coalesce(sum({m}), 0)::{'double' if m in MONEY else 'bigint'} as {m}"
            for m in measures]
    select = ", ".join(keys + sums)
    sql = f"select {select} from {view} where {where}"
    if keys:
        sql += f" group by {', '.join(keys)} order by {', '.join(order or keys)}"
    return (con or get_connection()).execute(sql, params).df()


def _ratio(num, den):
    num, den = np.asarray(num, float), np.asarray(den, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _add_rates(df):
    df["tool_adoption"] = _ratio(df["enabled_tool_calls"], df["enabled_eligible_calls"])
    df["interpreter_compliance"] = _ratio(df["not_enabled_interpreter_calls"],
                                          df["not_enabled_eligible_calls"])
    df["supported_rate"] = _ratio(df["supported_calls"], df["eligible_calls"])
    return df


def _keys(grain=None, by=None):
    keys = [GRAINS[grain]] if grain else []
    if by:
        keys += DIMENSIONS[by]
    return keys


# --- Filter helpers (not filtered themselves) -------------------------------

def filter_options(con=None) -> dict:
    """Values for the sidebar: date bounds, first rollout date, teams, sites, languages."""
    con = con or get_connection()
    lo, hi = con.execute("select min(call_date), max(call_date) from v_call_enriched").fetchone()
    return {
        "min_date": lo,
        "max_date": hi,
        "first_rollout_date": con.execute("select min(rollout_date) from dim_team").fetchone()[0],
        "teams": [r[0] for r in con.execute("select team from dim_team order by team").fetchall()],
        "sites": [r[0] for r in con.execute("select distinct site from dim_team order by 1").fetchall()],
        "languages": list(cfg.IN_SCOPE_LANGUAGES),
    }


def team_rollout_dates(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                       con=None) -> pd.DataFrame:
    """Tool rollout date per team (for chart markers), limited to the selected teams/sites.
    Dates and languages are accepted for a uniform signature but not applied."""
    where, params = _where(None, None, teams, sites, None)
    return (con or get_connection()).execute(
        f"select team, site, rollout_date from dim_team where {where} order by rollout_date, team",
        params).df()


# --- Adoption ----------------------------------------------------------------

def kpi_summary(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                con=None) -> pd.DataFrame:
    """One row: eligible calls, adoption rates, interpreter spend, cost avoided."""
    f = (start_date, end_date, teams, sites, languages)
    df = _add_rates(_sum_by("v_adoption_daily", [], ADOPTION_COUNTS, f, con))
    spend = interpreter_spend(*f, grain=None, con=con)
    avail = spend["tool_available"]
    df["interpreter_minutes"] = spend["interpreter_minutes"].sum()
    df["interpreter_spend_usd"] = spend["interpreter_spend_usd"].sum()
    df["interpreter_spend_where_tool_available_usd"] = spend.loc[avail, "interpreter_spend_usd"].sum()
    df["cost_avoided_usd"] = _sum_by("v_cost_avoided_daily", [], ["cost_avoided_usd"], f, con)[
        "cost_avoided_usd"].iloc[0]
    return df


def adoption_trend(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                   grain="week", by=None, con=None) -> pd.DataFrame:
    """Adoption, compliance and supported rate per day/week/month, optionally by a dimension."""
    f = (start_date, end_date, teams, sites, languages)
    return _add_rates(_sum_by("v_adoption_daily", _keys(grain, by), ADOPTION_COUNTS, f, con))


def adoption_by(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                by="team", con=None) -> pd.DataFrame:
    """Adoption, compliance and supported rate by team, supervisor, site, language or agent."""
    f = (start_date, end_date, teams, sites, languages)
    return _add_rates(_sum_by("v_adoption_daily", _keys(None, by), ADOPTION_COUNTS, f, con))


def agent_leaderboard(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                      min_enabled_calls=10, con=None) -> pd.DataFrame:
    """Agents with at least min_enabled_calls tool-enabled eligible calls, best adopters first."""
    df = adoption_by(start_date, end_date, teams, sites, languages, by="agent", con=con)
    df = df[df["enabled_eligible_calls"] >= min_enabled_calls]
    return df.sort_values(["tool_adoption", "enabled_eligible_calls"],
                          ascending=[False, False]).reset_index(drop=True)


def low_adopters(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                 min_enabled_calls=10, con=None) -> pd.DataFrame:
    """Agents with at least min_enabled_calls tool-enabled eligible calls, lowest adopters first."""
    df = adoption_by(start_date, end_date, teams, sites, languages, by="agent", con=con)
    df = df[df["enabled_eligible_calls"] >= min_enabled_calls]
    return df.sort_values(["tool_adoption", "enabled_eligible_calls"],
                          ascending=[True, False]).reset_index(drop=True)


def handling_path_trend(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                        grain="week", con=None) -> pd.DataFrame:
    """Eligible calls per period x handling path (long format), with share of the period."""
    f = (start_date, end_date, teams, sites, languages)
    period = GRAINS[grain]
    wide = _sum_by("v_adoption_daily", [period], ["tool_calls", "interpreter_calls",
                                                  "no_support_calls"], f, con)
    df = wide.melt(id_vars=period, var_name="handling_path", value_name="calls")
    df["handling_path"] = df["handling_path"].map({"tool_calls": "translation_tool",
                                                   "interpreter_calls": "interpreter_line",
                                                   "no_support_calls": "no_support"})
    df["calls"] = df["calls"].astype("int64")
    df["share_of_period"] = _ratio(df["calls"], df.groupby(period)["calls"].transform("sum"))
    return df.sort_values([period, "handling_path"], ascending=[True, False]).reset_index(drop=True)


def handling_path_mix(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                      con=None) -> pd.DataFrame:
    """Eligible calls by expected_support x handling_path, with share of eligible calls."""
    where, params = _where(start_date, end_date, teams, sites, languages,
                           date_col="call_date", lang_col="caller_language")
    df = (con or get_connection()).execute(f"""
        select expected_support, handling_path, count(*) as calls
        from v_call_enriched where eligible and {where}
        group by all order by expected_support desc, handling_path desc""", params).df()
    df["share_of_eligible"] = _ratio(df["calls"], np.full(len(df), df["calls"].sum()))
    return df


def ramp_curve(start_date=None, end_date=None, teams=None, sites=None, languages=None,
               bucket_days=7, by=None, con=None) -> pd.DataFrame:
    """Tool adoption by days since each agent's own tool_enabled_date, in buckets,
    optionally split by a dimension (e.g. by="team")."""
    where, params = _where(start_date, end_date, teams, sites, languages)
    dims = "".join(f", {k}" for k in _keys(None, by))
    df = (con or get_connection()).execute(f"""
        select floor(days_since_enabled / {int(bucket_days)}) * {int(bucket_days)} as days_since_enabled{dims},
               count(distinct agent_id) as agents,
               sum(enabled_eligible_calls)::bigint as enabled_eligible_calls,
               sum(enabled_tool_calls)::bigint as enabled_tool_calls
        from v_ramp_daily where {where}
        group by all order by all""", params).df()
    df["days_since_enabled"] = df["days_since_enabled"].astype(int)
    df["tool_adoption"] = _ratio(df["enabled_tool_calls"], df["enabled_eligible_calls"])
    return df


# --- Languages and routing -------------------------------------------------

def routing_mix(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                grain=None, con=None) -> pd.DataFrame:
    """In-scope calls by language: native-routed vs overflow, native share, overflow rate."""
    f = (start_date, end_date, teams, sites, languages)
    df = _sum_by("v_routing_daily", _keys(grain, "language"),
                 ["in_scope_calls", "native_routed_calls", "overflow_calls",
                  "native_handled_calls", "eligible_calls"], f, con)
    df["native_share"] = _ratio(df["native_handled_calls"], df["in_scope_calls"])
    df["overflow_rate"] = _ratio(df["overflow_calls"], df["in_scope_calls"])
    return df


def language_summary(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                     con=None) -> pd.DataFrame:
    """Per language: volume, native share, overflow rate, eligible calls and rates."""
    f = (start_date, end_date, teams, sites, languages)
    routing = routing_mix(*f, con=con).drop(columns=["eligible_calls"])
    adoption = adoption_by(*f, by="language", con=con)
    df = routing.merge(adoption[["language"] + ADOPTION_COUNTS], on="language", how="left")
    df[ADOPTION_COUNTS] = df[ADOPTION_COUNTS].fillna(0).astype("int64")
    return _add_rates(df)


# --- Operational impact ----------------------------------------------------

def operational_by_path(start_date=None, end_date=None, teams=None, sites=None,
                        languages=None, by_language=False, con=None) -> pd.DataFrame:
    """Handle time, hold, transfer rate and CSAT by segment (handling path,
    native_exempt or english), optionally by language."""
    f = (start_date, end_date, teams, sites, languages)
    keys = ["segment"] + (["language"] if by_language else [])
    df = _sum_by("v_operational_daily", keys,
                 ["calls", "talk_sec", "hold_sec", "handle_sec", "transferred_calls",
                  "csat_responses", "csat_sum"], f, con)
    for col in ["talk_sec", "hold_sec", "handle_sec"]:
        df[f"avg_{col}"] = _ratio(df[col], df["calls"])
    df["transfer_rate"] = _ratio(df["transferred_calls"], df["calls"])
    df["avg_csat"] = _ratio(df["csat_sum"], df["csat_responses"])
    return df.drop(columns=["talk_sec", "hold_sec", "handle_sec", "csat_sum"])


# --- Cost --------------------------------------------------------------------

def interpreter_spend(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                      grain="month", by_language=False, con=None) -> pd.DataFrame:
    """Interpreter calls, minutes and spend, split by tool_available
    (True = "interpreter used where tool was available")."""
    f = (start_date, end_date, teams, sites, languages)
    keys = _keys(grain) + (["language"] if by_language else []) + ["tool_available"]
    return _sum_by("v_interpreter_daily", keys,
                   ["interpreter_calls", "interpreter_minutes", "interpreter_spend_usd"], f, con)


def cost_avoided(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                 grain="month", by_language=False, con=None) -> pd.DataFrame:
    """Estimated interpreter cost avoided by tool-supported calls over time."""
    f = (start_date, end_date, teams, sites, languages)
    keys = _keys(grain) + (["language"] if by_language else [])
    return _sum_by("v_cost_avoided_daily", keys, ["tool_calls", "cost_avoided_usd"], f, con)


def cost_avoided_by_language(start_date=None, end_date=None, teams=None, sites=None,
                             languages=None, con=None) -> pd.DataFrame:
    """Cost avoided per language with the pre-rollout baseline used to compute it."""
    f = (start_date, end_date, teams, sites, languages)
    df = cost_avoided(*f, grain=None, by_language=True, con=con)
    baseline = (con or get_connection()).execute("select * from v_cost_baseline").df()
    return df.merge(baseline, on="language", how="left")


# --- Data quality ------------------------------------------------------------

def dq_session_links(start_date=None, end_date=None, teams=None, sites=None, languages=None,
                     con=None) -> pd.DataFrame:
    """Sessions by link method with ambiguous, pre-enablement, optional-use and
    call_id-not-found counts. Filters use session date and source language."""
    f = (start_date, end_date, teams, sites, languages)
    return _sum_by("v_dq_session_daily", ["link_method"],
                   ["sessions", "ambiguous_sessions", "before_enablement_sessions",
                    "optional_use_sessions", "call_id_not_found_sessions"], f, con)


def dq_sessions_before_enablement(start_date=None, end_date=None, teams=None, sites=None,
                                  languages=None, con=None) -> pd.DataFrame:
    """Session rows dated before the agent's tool_enabled_date (excluded from adoption)."""
    where, params = _where(start_date, end_date, teams, sites, languages,
                           date_col="session_date", lang_col="source_language")
    return (con or get_connection()).execute(f"""
        select session_id, agent_id, agent_name, team, site, session_start_ts,
               source_language, link_method, linked_call_id, tool_enabled_date
        from v_session_linked
        where before_enablement and {where}
        order by session_start_ts""", params).df()


def dq_agents_without_language_records(start_date=None, end_date=None, teams=None, sites=None,
                                       languages=None, con=None) -> pd.DataFrame:
    """Agents employed in the date range with no proficiency record for any of
    the selected languages (all treated as 'none')."""
    where, params = _where(None, None, teams, sites, languages)
    emp, emp_params = ["true"], []
    if end_date is not None:
        emp.append("hire_date <= ?")
        emp_params.append(pd.Timestamp(end_date).date())
    if start_date is not None:
        emp.append("(termination_date is null or termination_date > ?)")
        emp_params.append(pd.Timestamp(start_date).date())
    return (con or get_connection()).execute(f"""
        select agent_id, agent_name, team, supervisor, site, count(*) as languages_missing
        from v_dq_agent_language
        where {where} and {' and '.join(emp)}
        group by all
        having not bool_or(has_record)
        order by agent_id""", params + emp_params).df()


def dq_orphan_interpreter_rows(start_date=None, end_date=None, teams=None, sites=None,
                               languages=None, con=None) -> pd.DataFrame:
    """Interpreter rows with no matching call. These rows have no date, team or
    language, so the filters cannot apply; all orphans are always returned."""
    return (con or get_connection()).execute(
        "select * from v_dq_orphan_interpreter order by interpreter_call_id").df()


def dq_summary(start_date=None, end_date=None, teams=None, sites=None, languages=None,
               con=None) -> pd.DataFrame:
    """Data quality headline counts as (metric, value) rows."""
    f = (start_date, end_date, teams, sites, languages)
    links = dq_session_links(*f, con=con).set_index("link_method")
    count = lambda method: int(links["sessions"].get(method, 0))  # noqa: E731
    rows = [
        ("Sessions linked by call_id", count("call_id")),
        ("Sessions linked by time window", count("time_window")),
        ("Unlinked practice sessions", count("unlinked")),
        ("Ambiguous time-window links", int(links["ambiguous_sessions"].sum())),
        ("Sessions before tool_enabled_date", int(links["before_enablement_sessions"].sum())),
        ("Native optional-use sessions", int(links["optional_use_sessions"].sum())),
        ("Sessions whose call_id is not in fact_call", int(links["call_id_not_found_sessions"].sum())),
        ("Agents with no language records", len(dq_agents_without_language_records(*f, con=con))),
        ("Orphan interpreter rows (unfiltered)", len(dq_orphan_interpreter_rows(*f, con=con))),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])
