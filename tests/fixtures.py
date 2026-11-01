"""Small hand-built datasets with known answers for metric tests.

Agents (all with full schedules so the schema matches the generator):
    NAT  team T1 / site S1, enabled 2026-05-01, native Spanish, Mandarin 'none'
    BI   team T2 / site S2, enabled 2026-06-01, native Spanish and Portuguese
    FLU  team T1 / site S1, enabled 2026-05-01, fluent Spanish
    CON  team T2 / site S2, enabled 2026-06-01, conversational Spanish
    MIS  team T2 / site S2, enabled 2026-05-01, no proficiency records at all
    OFF  team T2 / site S2, tool_enabled_date blank, Spanish 'none'
Teams: T1 rollout 2026-05-01 (Sup One, S1), T2 rollout 2026-06-01 (Sup Two, S2).
"""

from datetime import date

import pandas as pd

import config as cfg

AGENTS = {  # agent_id: (team, enabled)
    "NAT": ("T1", date(2026, 5, 1)),
    "BI": ("T2", date(2026, 6, 1)),
    "FLU": ("T1", date(2026, 5, 1)),
    "CON": ("T2", date(2026, 6, 1)),
    "MIS": ("T2", date(2026, 5, 1)),
    "OFF": ("T2", None),
}
TEAMS = {"T1": ("Sup One", "S1", date(2026, 5, 1)), "T2": ("Sup Two", "S2", date(2026, 6, 1))}
PROFICIENCY = [
    ("NAT", "Spanish", "native"), ("NAT", "Mandarin", "none"),
    ("BI", "Spanish", "native"), ("BI", "Portuguese", "native"),
    ("FLU", "Spanish", "fluent"),
    ("CON", "Spanish", "conversational"),
    ("OFF", "Spanish", "none"),
]


def call(call_id, agent_id, language, start, talk=500, hold=40, wrap=60,
         transferred=False, csat=None, routing_reason=None):
    """One fact_call row; the call lasts talk + hold seconds."""
    start = pd.Timestamp(start)
    if routing_reason is None and language != "English":
        native = (agent_id, language, "native") in PROFICIENCY
        routing_reason = "native" if native else "overflow"
    return {
        "call_id": call_id, "call_start_ts": start,
        "call_end_ts": start + pd.Timedelta(seconds=talk + hold),
        "caller_language": language, "queue": "Billing", "agent_id": agent_id,
        "routing_reason": routing_reason, "talk_sec": talk, "hold_sec": hold,
        "handle_sec": talk + hold + wrap, "transferred": transferred,
        "disposition": "Transferred" if transferred else "Resolved", "csat": csat,
    }


def session(session_id, agent_id, start, call_id=None, minutes=5, language="Spanish"):
    start = pd.Timestamp(start)
    return {
        "session_id": session_id, "agent_id": agent_id, "call_id": call_id,
        "session_start_ts": start, "session_end_ts": start + pd.Timedelta(minutes=minutes),
        "source_language": language, "target_language": "English",
        "error_flag": False, "agent_rating": None,
    }


def interpreter(interpreter_call_id, call_id, minutes):
    return {"interpreter_call_id": interpreter_call_id, "call_id": call_id,
            "vendor": "Test Vendor", "minutes": minutes,
            "cost_usd": round(minutes * cfg.INTERPRETER_COST_PER_MIN, 2)}


def build_tables(calls, sessions=(), interpreters=()) -> dict[str, pd.DataFrame]:
    """All six raw tables with the standard agents plus the given facts."""
    agents = pd.DataFrame([{
        "agent_id": a, "agent_name": f"Agent {a}", "team": team,
        "supervisor": TEAMS[team][0], "site": TEAMS[team][1],
        "hire_date": date(2025, 1, 1), "tool_enabled_date": enabled,
        "status": "active", "termination_date": None, "days_off": "Sat,Sun",
        "shift_start": "08:00", "shift_end": "16:00", "lunch_start": "12:00",
    } for a, (team, enabled) in AGENTS.items()])
    agents["tool_enabled_date"] = pd.to_datetime(agents["tool_enabled_date"]).dt.date
    agents["termination_date"] = pd.to_datetime(agents["termination_date"]).dt.date
    teams = pd.DataFrame([{"team": t, "supervisor": s, "site": site, "rollout_date": r}
                          for t, (s, site, r) in TEAMS.items()])
    prof = pd.DataFrame(PROFICIENCY, columns=["agent_id", "language", "proficiency_level"])

    call_cols = list(call("x", "NAT", "English", "2026-01-01"))
    sess_cols = list(session("x", "NAT", "2026-01-01"))
    interp_cols = list(interpreter("x", "x", 1))
    calls = pd.DataFrame(list(calls), columns=call_cols)
    calls["csat"] = calls["csat"].astype("Int64")
    sessions = pd.DataFrame(list(sessions), columns=sess_cols)
    sessions["call_id"] = sessions["call_id"].astype(object)
    sessions["agent_rating"] = sessions["agent_rating"].astype("Int64")
    for col in ["session_start_ts", "session_end_ts"]:
        sessions[col] = pd.to_datetime(sessions[col])
    interps = pd.DataFrame(list(interpreters), columns=interp_cols)
    return {"dim_agent": agents, "dim_team": teams, "agent_language_proficiency": prof,
            "fact_call": calls, "fact_translation_session": sessions,
            "fact_interpreter_usage": interps}
