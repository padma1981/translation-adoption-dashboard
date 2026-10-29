"""Generate synthetic Parquet data for the translation adoption dashboard.

Run from the repo root:  python -m data_gen.generate

Writes dim_agent, agent_language_proficiency, fact_call,
fact_translation_session and fact_interpreter_usage to config.RAW_DATA_DIR.
All values are synthetic and reproducible from config.SEED.
"""

from datetime import date, timedelta
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg  # noqa: E402

PATHS = ["native", "translation_tool", "interpreter_line", "no_support"]


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def build_agents(rng: np.random.Generator, fake: Faker) -> pd.DataFrame:
    """Agents with team, site, supervisor, hire/termination and enablement dates."""
    teams = list(cfg.TEAMS)
    supervisors = {t: fake.unique.name() for t in teams}
    n = cfg.N_AGENTS
    team = np.array([teams[i % len(teams)] for i in range(n)])
    rng.shuffle(team)

    range_days = (cfg.END_DATE - cfg.START_DATE).days
    hire = [cfg.START_DATE - timedelta(days=int(rng.integers(60, 2000))) for _ in range(n)]
    late_hires = rng.choice(n, int(n * cfg.MID_RANGE_HIRE_SHARE), replace=False)
    for i in late_hires:
        hire[i] = cfg.START_DATE + timedelta(days=int(rng.integers(10, range_days - 30)))

    # Termination date is internal only (dim_agent exposes status).
    term = [None] * n
    candidates = np.setdiff1d(np.arange(n), late_hires)
    for i in rng.choice(candidates, int(n * cfg.TERMINATED_SHARE), replace=False):
        term[i] = cfg.START_DATE + timedelta(days=int(rng.integers(20, range_days - 10)))

    enabled = []
    for t, h, x in zip(team, hire, term):
        e = max(cfg.TEAM_ROLLOUT_DATES[t], h)
        enabled.append(None if (x is not None and x <= e) else e)

    propensity = rng.beta(*cfg.AGENT_PROPENSITY_BETA, size=n)
    a, b = cfg.AGENT_PROPENSITY_BETA
    propensity = propensity / (a / (a + b))

    return pd.DataFrame({
        "agent_id": [f"A{i + 1:03d}" for i in range(n)],
        "agent_name": [fake.unique.name() for _ in range(n)],
        "team": team,
        "supervisor": [supervisors[t] for t in team],
        "site": [cfg.TEAMS[t] for t in team],
        "hire_date": hire,
        "tool_enabled_date": enabled,
        "status": ["terminated" if x is not None else "active" for x in term],
        "_term_date": term,
        "_propensity": propensity,
    })


def build_proficiency(rng: np.random.Generator, agents: pd.DataFrame) -> pd.DataFrame:
    """Native speakers per NATIVE_AGENT_PLAN, plus non-native levels for others."""
    # Natives come from agents employed for the whole range, spread across teams.
    stable = agents[(agents["status"] == "active") & (agents["hire_date"] < cfg.START_DATE)]
    stable = stable.sample(frac=1, random_state=int(rng.integers(1e9)))
    picked, used_teams = [], set()
    for _, row in stable.iterrows():
        if len(picked) == len(cfg.NATIVE_AGENT_PLAN):
            break
        if row["team"] not in used_teams or len(used_teams) == len(cfg.TEAMS):
            picked.append(row["agent_id"])
            used_teams.add(row["team"])
    native_map = dict(zip(picked, cfg.NATIVE_AGENT_PLAN))

    rows = []
    for agent_id in agents["agent_id"]:
        natives = native_map.get(agent_id, ())
        if not natives and rng.random() < cfg.MISSING_PROFICIENCY_SHARE:
            continue  # no records at all -> treated as "none"
        for lang in cfg.IN_SCOPE_LANGUAGES:
            if lang in natives:
                level = "native"
            else:
                probs = cfg.NON_NATIVE_PROFICIENCY[lang]
                level = rng.choice(list(probs), p=list(probs.values()))
                # Skip some "none" rows so missing records appear naturally.
                if level == "none" and rng.random() < 0.3:
                    continue
            rows.append((agent_id, lang, level))
    return pd.DataFrame(rows, columns=["agent_id", "language", "proficiency_level"])


def build_calls(rng: np.random.Generator, agents: pd.DataFrame,
                prof: pd.DataFrame) -> pd.DataFrame:
    """Calls with routing, eligibility-driven handling path, and durations."""
    natives = prof[prof["proficiency_level"] == "native"]
    native_set = set(zip(natives["agent_id"], natives["language"]))
    agent_ids = agents["agent_id"].to_numpy()
    langs = list(cfg.LANGUAGE_MIX)
    lang_p = list(cfg.LANGUAGE_MIX.values())

    frames = []
    for d in _days(cfg.START_DATE, cfg.END_DATE):
        employed = (agents["hire_date"] <= d) & agents["_term_date"].map(
            lambda x: x is None or d < x)
        avail = agent_ids[employed.to_numpy()]
        n = rng.poisson(cfg.CALLS_PER_DAY)
        call_lang = rng.choice(langs, size=n, p=lang_p)
        assigned = rng.choice(avail, size=n)
        for lang in cfg.IN_SCOPE_LANGUAGES:
            idx = np.flatnonzero(call_lang == lang)
            nat = np.array([a for a in avail if (a, lang) in native_set])
            non = np.array([a for a in avail if (a, lang) not in native_set])
            to_native = rng.random(len(idx)) < cfg.NATIVE_ROUTING_RATE if len(nat) else \
                np.zeros(len(idx), bool)
            assigned[idx[to_native]] = rng.choice(nat, size=to_native.sum()) if len(nat) else []
            assigned[idx[~to_native]] = rng.choice(non, size=(~to_native).sum())
        frames.append(pd.DataFrame({"call_date": d, "caller_language": call_lang,
                                    "agent_id": assigned}))
    calls = pd.concat(frames, ignore_index=True)
    n = len(calls)
    calls["queue"] = rng.choice(cfg.QUEUES, size=n, p=cfg.QUEUE_WEIGHTS)

    # Eligibility and handling path (generator-side truth; metrics re-derive it).
    a = agents.set_index("agent_id")
    calls = calls.join(a[["team", "tool_enabled_date", "_propensity"]], on="agent_id")
    in_scope = calls["caller_language"].isin(cfg.IN_SCOPE_LANGUAGES).to_numpy()
    is_native = np.array([(ag, lg) in native_set
                          for ag, lg in zip(calls["agent_id"], calls["caller_language"])])
    eligible = in_scope & ~is_native
    enabled = calls["tool_enabled_date"].notna() & (
        calls["call_date"] >= calls["tool_enabled_date"].fillna(date.max))
    enabled = enabled.to_numpy()

    days_on = np.array([(c - e).days if e is not None and c >= e else 0
                        for c, e in zip(calls["call_date"], calls["tool_enabled_date"])])
    target = calls["caller_language"].map(cfg.ADOPTION_TARGET).fillna(0).to_numpy()
    team_factor = np.where(calls["team"].isin(cfg.LAGGING_TEAMS), cfg.LAGGING_TEAM_FACTOR, 1.0)
    p_tool = np.clip(target * team_factor * calls["_propensity"].to_numpy()
                     * (1 - np.exp(-days_on / cfg.RAMP_TAU_DAYS)), 0, 0.98)

    r = rng.random(n)
    uses_tool = eligible & enabled & (r < p_tool)
    interp = eligible & ~uses_tool & (rng.random(n) < cfg.INTERPRETER_SHARE_OF_NON_TOOL)
    path = np.full(n, "native", dtype=object)
    path[eligible] = "no_support"
    path[interp] = "interpreter_line"
    path[uses_tool] = "translation_tool"
    optional_use = in_scope & is_native & enabled & (rng.random(n) < cfg.NATIVE_OPTIONAL_USE_RATE)
    calls["_path"] = path
    calls["_has_session"] = uses_tool | optional_use

    # Durations by path.
    s = cfg.TALK_SEC_SIGMA
    talk_mean = pd.Series(path).map(cfg.TALK_SEC_MEAN).to_numpy()
    calls["talk_sec"] = np.round(rng.lognormal(np.log(talk_mean) - s * s / 2, s)).astype(int)
    hold_mean = pd.Series(path).map(cfg.HOLD_SEC_MEAN).to_numpy()
    calls["hold_sec"] = np.round(rng.exponential(hold_mean)).astype(int)
    wrap = rng.integers(*cfg.WRAP_SEC_RANGE, size=n)
    calls["handle_sec"] = calls["talk_sec"] + calls["hold_sec"] + wrap

    calls["transferred"] = rng.random(n) < pd.Series(path).map(cfg.TRANSFER_RATE).to_numpy()
    calls["disposition"] = np.where(
        calls["transferred"], "Transferred",
        rng.choice(cfg.DISPOSITIONS, size=n, p=cfg.DISPOSITION_WEIGHTS))
    csat_mean = pd.Series(path).map(cfg.CSAT_MEAN).to_numpy()
    csat = np.clip(np.round(rng.normal(csat_mean, 0.9)), 1, 5)
    calls["csat"] = pd.array(np.where(rng.random(n) < cfg.CSAT_RESPONSE_RATE, csat, np.nan),
                             dtype="Int64")

    return _schedule(rng, calls)


def _schedule(rng: np.random.Generator, calls: pd.DataFrame) -> pd.DataFrame:
    """Lay each agent's calls end to end within the day so calls never overlap."""
    calls["_order"] = rng.random(len(calls))
    calls = calls.sort_values(["agent_id", "call_date", "_order"]).reset_index(drop=True)
    on_call = calls["talk_sec"] + calls["hold_sec"]
    gap = pd.Series(rng.integers(*cfg.GAP_BETWEEN_CALLS_SEC, size=len(calls)))
    g = calls.groupby(["agent_id", "call_date"], sort=False)
    # Shrink gaps for busy agent-days so the shift fits in SHIFT_LENGTH_HOURS.
    slack = (cfg.SHIFT_LENGTH_HOURS * 3600 - on_call.groupby(g.ngroup()).transform("sum")).clip(lower=0)
    gap = (gap * np.minimum(1, slack / gap.groupby(g.ngroup()).transform("sum"))).round()
    offset = (on_call + gap).groupby([calls["agent_id"], calls["call_date"]]).cumsum() - (on_call + gap)
    lo, hi = cfg.SHIFT_START_HOUR_RANGE
    shift = pd.Series(rng.integers(lo * 3600, hi * 3600, size=len(calls))).groupby(
        g.ngroup()).transform("first")
    day = pd.to_datetime(calls["call_date"])
    calls["call_start_ts"] = day + pd.to_timedelta(shift + offset, unit="s")
    calls["call_end_ts"] = calls["call_start_ts"] + pd.to_timedelta(on_call, unit="s")
    calls = calls.sort_values("call_start_ts").reset_index(drop=True)
    calls["call_id"] = [f"C{i + 1:07d}" for i in range(len(calls))]
    return calls


def build_sessions(rng: np.random.Generator, calls: pd.DataFrame) -> pd.DataFrame:
    """One session per tool call, some with null call_id, plus unlinkable orphans."""
    c = calls[calls["_has_session"]]
    n = len(c)
    dur = (c["call_end_ts"] - c["call_start_ts"]).dt.total_seconds().to_numpy()
    lead = np.minimum(rng.uniform(5, 60, n), dur * 0.2)
    start = c["call_start_ts"].to_numpy() + pd.to_timedelta(lead, unit="s").to_numpy()
    length = (dur - lead) * rng.uniform(0.6, 0.95, n)
    sessions = pd.DataFrame({
        "agent_id": c["agent_id"].to_numpy(),
        "call_id": c["call_id"].to_numpy(),
        "session_start_ts": start,
        "session_end_ts": start + pd.to_timedelta(length, unit="s").to_numpy(),
        "source_language": c["caller_language"].to_numpy(),
    })
    sessions.loc[rng.random(n) < cfg.SESSION_NULL_CALL_ID_SHARE, "call_id"] = None

    # Orphans: sessions after an agent's last call of the day (practice/tests).
    n_orphan = int(n * cfg.ORPHAN_SESSION_SHARE)
    last = calls.groupby(["agent_id", calls["call_start_ts"].dt.date])["call_end_ts"].max()
    tool_agents = set(c["agent_id"])
    last = last[last.index.get_level_values(0).isin(tool_agents)]
    pick = last.sample(n_orphan, random_state=int(rng.integers(1e9)))
    o_start = pick.to_numpy() + pd.to_timedelta(rng.uniform(600, 7200, n_orphan), unit="s").to_numpy()
    orphans = pd.DataFrame({
        "agent_id": pick.index.get_level_values(0),
        "call_id": None,
        "session_start_ts": o_start,
        "session_end_ts": o_start + pd.to_timedelta(rng.uniform(60, 600, n_orphan), unit="s").to_numpy(),
        "source_language": rng.choice(cfg.IN_SCOPE_LANGUAGES, n_orphan),
    })
    sessions = pd.concat([sessions, orphans], ignore_index=True)
    sessions = sessions.sort_values("session_start_ts").reset_index(drop=True)

    m = len(sessions)
    sessions.insert(0, "session_id", [f"S{i + 1:07d}" for i in range(m)])
    sessions["target_language"] = cfg.AGENT_LANGUAGE
    err_p = sessions["source_language"].map(cfg.SESSION_ERROR_RATE_BY_LANGUAGE).fillna(
        cfg.SESSION_ERROR_RATE).to_numpy()
    sessions["error_flag"] = rng.random(m) < err_p
    rating = np.clip(np.round(rng.normal(np.where(sessions["error_flag"], 2.5, 4.2), 0.8)), 1, 5)
    sessions["agent_rating"] = pd.array(
        np.where(rng.random(m) < cfg.AGENT_RATING_RESPONSE_RATE, rating, np.nan), dtype="Int64")
    return sessions


def build_interpreter(rng: np.random.Generator, calls: pd.DataFrame) -> pd.DataFrame:
    """One vendor record per interpreter-line call."""
    c = calls[calls["_path"] == "interpreter_line"]
    n = len(c)
    minutes = np.maximum(1, np.ceil((c["talk_sec"].to_numpy() - rng.uniform(30, 90, n)) / 60))
    return pd.DataFrame({
        "interpreter_call_id": [f"I{i + 1:07d}" for i in range(n)],
        "call_id": c["call_id"].to_numpy(),
        "vendor": rng.choice(cfg.INTERPRETER_VENDORS, n, p=cfg.INTERPRETER_VENDOR_WEIGHTS),
        "minutes": minutes.astype(int),
        "cost_usd": np.round(minutes * cfg.INTERPRETER_COST_PER_MIN, 2),
    })


def main() -> None:
    rng = np.random.default_rng(cfg.SEED)
    Faker.seed(cfg.SEED)
    fake = Faker("en_US")

    agents = build_agents(rng, fake)
    prof = build_proficiency(rng, agents)
    calls = build_calls(rng, agents, prof)
    sessions = build_sessions(rng, calls)
    interp = build_interpreter(rng, calls)

    out = Path(__file__).resolve().parents[1] / cfg.RAW_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    call_cols = ["call_id", "call_start_ts", "call_end_ts", "caller_language", "queue",
                 "agent_id", "talk_sec", "hold_sec", "handle_sec", "transferred",
                 "disposition", "csat"]
    tables = {
        "dim_agent": agents.drop(columns=["_term_date", "_propensity"]),
        "agent_language_proficiency": prof,
        "fact_call": calls[call_cols],
        "fact_translation_session": sessions,
        "fact_interpreter_usage": interp,
    }
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False, compression="zstd")
        print(f"{name:28s} {len(df):>8,} rows")

    _print_summary(agents, prof, calls, sessions)


def _print_summary(agents, prof, calls, sessions) -> None:
    """Quick sanity check of the generated assumptions."""
    natives = prof[prof["proficiency_level"] == "native"]
    n_native = natives["agent_id"].nunique()
    print(f"\nNative agents: {n_native} of {len(agents)} ({n_native / len(agents):.1%})")
    print(natives.groupby("language")["agent_id"].nunique().to_string())
    multi = (natives.groupby("agent_id").size() > 1).sum()
    print(f"Agents native in 2+ languages: {multi}")

    in_scope = calls[calls["caller_language"].isin(cfg.IN_SCOPE_LANGUAGES)]
    elig = in_scope[in_scope["_path"] != "native"]
    print(f"\nIn-scope calls: {len(in_scope):,}; to native agent: "
          f"{(in_scope['_path'] == 'native').mean():.1%}; eligible: {len(elig):,}")
    print("Eligible handling path mix:")
    print(elig["_path"].value_counts(normalize=True).round(3).to_string())
    post = elig[elig["call_start_ts"].dt.date >= date(2026, 9, 1)]
    print("\nSeptember adoption by language:")
    print(post.groupby("caller_language")["_path"].apply(
        lambda p: (p == "translation_tool").mean()).round(3).to_string())
    print("September adoption by team:")
    print(post.groupby("team")["_path"].apply(
        lambda p: (p == "translation_tool").mean()).round(3).to_string())
    print(f"\nSessions with null call_id: {sessions['call_id'].isna().sum():,}")


if __name__ == "__main__":
    main()
