"""Consistency checks for the generated tables.

Each check takes the dict of tables (as written to Parquet) and returns
(passed, detail). run_all() runs every check; tests/test_generated_data.py
runs them against data/raw/.
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg  # noqa: E402

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _sec(hhmm: pd.Series) -> pd.Series:
    parts = hhmm.str.split(":", expand=True).astype(int)
    return parts[0] * 3600 + parts[1] * 60


def _calls_with_agent(t: dict) -> pd.DataFrame:
    a = t["dim_agent"].set_index("agent_id")
    c = t["fact_call"].join(a[["hire_date", "termination_date", "days_off", "shift_start",
                               "shift_end", "lunch_start"]], on="agent_id")
    c["call_date"] = c["call_start_ts"].dt.normalize()
    return c


def _result(bad: int, what: str) -> tuple[bool, str]:
    return bad == 0, f"{bad:,} {what}" if bad else ""


def no_overlapping_calls(t):
    """An agent's next call starts after the previous call's end plus wrap-up."""
    c = t["fact_call"].sort_values(["agent_id", "call_start_ts"])
    free_at = c["call_start_ts"] + pd.to_timedelta(c["handle_sec"], unit="s")
    prev_free = free_at.groupby(c["agent_id"]).shift()
    return _result(int((c["call_start_ts"] < prev_free).sum()), "calls overlap")


def nothing_crosses_midnight(t):
    c, s = t["fact_call"], t["fact_translation_session"]
    bad = (c["call_start_ts"].dt.date != (c["call_start_ts"] + pd.to_timedelta(
        c["handle_sec"], unit="s")).dt.date).sum()
    bad += (s["session_start_ts"].dt.date != s["session_end_ts"].dt.date).sum()
    return _result(int(bad), "calls/sessions cross midnight")


def shifts_end_by_1900(t):
    """Every shift ends by 19:00 and every call arrives between 08:00 and 19:00."""
    a, c = t["dim_agent"], t["fact_call"]
    bad = int((_sec(a["shift_end"]) > 19 * 3600).sum())
    tod = c["call_start_ts"] - c["call_start_ts"].dt.normalize()
    bad += int(((tod < pd.Timedelta(hours=8)) | (tod >= pd.Timedelta(hours=19))).sum())
    return _result(bad, "shifts end after 19:00 or calls start outside 08:00-19:00")


def linked_sessions_inside_call(t):
    s = t["fact_translation_session"].dropna(subset=["call_id"])
    m = s.join(t["fact_call"].set_index("call_id")[["agent_id", "call_start_ts", "call_end_ts"]],
               on="call_id", rsuffix="_call")
    bad = ((m["session_start_ts"] < m["call_start_ts"]) | (m["session_start_ts"] > m["call_end_ts"])
           | (m["agent_id"] != m["agent_id_call"])).sum()
    return _result(int(bad), "linked sessions start outside their call")


def routed_to_on_shift_agent(t):
    """Calls start on a working day, after hire, inside the shift and not at lunch.

    Busy agents are covered by no_overlapping_calls."""
    c = _calls_with_agent(t)
    tod = (c["call_start_ts"] - c["call_date"]).dt.total_seconds()
    day = c["call_start_ts"].dt.weekday.map(dict(enumerate(DAY_NAMES)))
    off = np.array([d in o.split(",") for d, o in zip(day, c["days_off"])])
    lunch = _sec(c["lunch_start"])
    bad = (off | (c["call_date"] < pd.to_datetime(c["hire_date"]))
           | (tod < _sec(c["shift_start"])) | (tod >= _sec(c["shift_end"]))
           | ((tod >= lunch) & (tod < lunch + cfg.LUNCH_MIN * 60)))
    return _result(int(bad.sum()), "calls routed to an off-shift agent")


def terminated_agents_inactive(t):
    a = t["dim_agent"].dropna(subset=["termination_date"]).set_index("agent_id")
    term = pd.to_datetime(a["termination_date"])
    c, s = t["fact_call"], t["fact_translation_session"]
    bad = (c["call_start_ts"].dt.normalize() >= c["agent_id"].map(term)).sum()
    bad += (s["session_start_ts"].dt.normalize() >= s["agent_id"].map(term)).sum()
    return _result(int(bad), "calls/sessions on or after termination_date")


def interpreter_minutes_fit_call(t):
    i = t["fact_interpreter_usage"].join(
        t["fact_call"].set_index("call_id")[["talk_sec", "hold_sec"]], on="call_id")
    bad = (i["minutes"] * 60 > i["talk_sec"] + i["hold_sec"] + 60).sum()
    return _result(int(bad), "interpreter records exceed talk + hold + 1 min")


def durations_consistent(t):
    c = t["fact_call"]
    dur = (c["call_end_ts"] - c["call_start_ts"]).dt.total_seconds()
    wrap = c["handle_sec"] - c["talk_sec"] - c["hold_sec"]
    lo, hi = cfg.WRAP_SEC_RANGE
    bad = ((dur != c["talk_sec"] + c["hold_sec"]) | (wrap < lo) | (wrap > hi)).sum()
    return _result(int(bad), "calls with inconsistent durations")


def transferred_matches_disposition(t):
    c = t["fact_call"]
    return _result(int((c["transferred"] != (c["disposition"] == "Transferred")).sum()),
                   "calls where transferred != (disposition == 'Transferred')")


ALL_CHECKS = [no_overlapping_calls, nothing_crosses_midnight, shifts_end_by_1900,
              linked_sessions_inside_call, routed_to_on_shift_agent,
              terminated_agents_inactive, interpreter_minutes_fit_call,
              durations_consistent, transferred_matches_disposition]


def run_all(tables: dict) -> list[tuple[str, bool, str]]:
    return [(f.__name__, *f(tables)) for f in ALL_CHECKS]


def load_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in sorted(Path(raw_dir).glob("*.parquet"))}
