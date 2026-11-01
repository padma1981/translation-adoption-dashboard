"""Generate synthetic Parquet data for the translation adoption dashboard.

Run from the repo root:  python -m data_gen.generate

Writes dim_agent, dim_team, agent_language_proficiency, fact_call,
fact_translation_session and fact_interpreter_usage to config.RAW_DATA_DIR,
then runs the data checks in data_gen/checks.py.
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
from data_gen import checks  # noqa: E402

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CALL_COLS = ["call_id", "call_start_ts", "call_end_ts", "caller_language", "queue",
             "agent_id", "routing_reason", "talk_sec", "hold_sec", "handle_sec",
             "transferred", "disposition", "csat"]


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def hhmm_to_sec(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def _sec_to_hhmm(x: int) -> str:
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}"


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

    # First day the agent no longer works (no calls or sessions on/after it).
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
        "termination_date": term,
        "_propensity": propensity,
    })


def build_teams(agents: pd.DataFrame) -> pd.DataFrame:
    """One row per team with its supervisor, site and tool rollout date."""
    t = agents.groupby("team", as_index=False)[["supervisor", "site"]].first()
    t["rollout_date"] = t["team"].map(cfg.TEAM_ROLLOUT_DATES)
    return t.sort_values("rollout_date").reset_index(drop=True)


def add_schedules(rng: np.random.Generator, agents: pd.DataFrame) -> pd.DataFrame:
    """5-day week with 2 consecutive days off, staggered 8-hour shift, 30-min lunch."""
    n = len(agents)
    options = list(cfg.DAYS_OFF_OPTIONS)
    pick = rng.choice(len(options), size=n, p=list(cfg.DAYS_OFF_OPTIONS.values()))
    lo, hi = (hhmm_to_sec(s) for s in cfg.SHIFT_START_RANGE)
    start = rng.choice(np.arange(lo, hi + 1, cfg.SHIFT_START_STEP_MIN * 60), size=n)
    l_lo, l_hi = cfg.LUNCH_OFFSET_RANGE_MIN
    lunch = start + rng.choice(np.arange(l_lo, l_hi + 1, 15), size=n) * 60
    agents["days_off"] = [",".join(options[i]) for i in pick]
    agents["shift_start"] = [_sec_to_hhmm(int(s)) for s in start]
    agents["shift_end"] = [_sec_to_hhmm(int(s) + cfg.SHIFT_HOURS * 3600) for s in start]
    agents["lunch_start"] = [_sec_to_hhmm(int(s)) for s in lunch]
    return agents


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


def build_arrivals(rng: np.random.Generator) -> pd.DataFrame:
    """Call arrivals per day on the intraday curve, lower volume on weekends."""
    hours = np.array(list(cfg.INTRADAY_ARRIVAL_WEIGHTS))
    hour_p = list(cfg.INTRADAY_ARRIVAL_WEIGHTS.values())
    langs, lang_p = list(cfg.LANGUAGE_MIX), list(cfg.LANGUAGE_MIX.values())
    frames = []
    for d in _days(cfg.START_DATE, cfg.END_DATE):
        mean = cfg.CALLS_PER_DAY * (cfg.WEEKEND_VOLUME_FACTOR if d.weekday() >= 5 else 1)
        n = rng.poisson(mean)
        sec = np.sort(rng.choice(hours, size=n, p=hour_p) * 3600 + rng.integers(0, 3600, n))
        frames.append(pd.DataFrame({"call_date": d, "arrival_sec": sec,
                                    "caller_language": rng.choice(langs, size=n, p=lang_p)}))
    return pd.concat(frames, ignore_index=True)


class _Floor:
    """Agent availability for one day: who is on shift, at lunch, or busy."""

    def __init__(self, present, shift_start, shift_end, lunch_start, lunch_end):
        self.present = present
        self.shift_end = shift_end
        self.lunch_start, self.lunch_end = lunch_start, lunch_end
        # Time each agent is next free (call end + wrap-up); starts at shift start.
        self.free_at = np.where(present, shift_start, np.inf).astype(float)

    def pick(self, t, pool):
        """Longest-idle free, on-shift agent in pool at time t, or None."""
        ok = (pool & self.present & (self.free_at <= t) & (t < self.shift_end)
              & ~((self.lunch_start <= t) & (t < self.lunch_end)))
        if not ok.any():
            return None
        idle_since = np.where((self.lunch_end <= t) & (self.free_at < self.lunch_end),
                              self.lunch_end, self.free_at)
        return int(np.argmin(np.where(ok, idle_since, np.inf)))

    def next_free(self, t, pool):
        """Earliest time >= t that some agent in pool becomes routable (inf if none)."""
        c = np.maximum(t, self.free_at)
        c = np.where((self.lunch_start <= c) & (c < self.lunch_end), self.lunch_end, c)
        c = np.where(pool & self.present & (c < self.shift_end), c, np.inf)
        return float(c.min())


def route_calls(rng: np.random.Generator, arrivals: pd.DataFrame, agents: pd.DataFrame,
                native_set: set) -> pd.DataFrame:
    """Route arrivals in time order and decide handling path and durations per call."""
    n = len(arrivals)
    z_talk = rng.standard_normal(n)
    e_hold = rng.exponential(1.0, n)
    wrap = rng.integers(cfg.WRAP_SEC_RANGE[0], cfg.WRAP_SEC_RANGE[1] + 1, n)
    u_tool, u_interp, u_opt = rng.random(n), rng.random(n), rng.random(n)

    ids = agents["agent_id"].to_numpy()
    all_pool = np.ones(len(ids), bool)
    native_mask = {lg: np.array([(a, lg) in native_set for a in ids])
                   for lg in cfg.IN_SCOPE_LANGUAGES}
    shift_start = agents["shift_start"].map(hhmm_to_sec).to_numpy()
    shift_end = shift_start + cfg.SHIFT_HOURS * 3600
    lunch_start = agents["lunch_start"].map(hhmm_to_sec).to_numpy()
    lunch_end = lunch_start + cfg.LUNCH_MIN * 60
    works = {wd: ~agents["days_off"].str.contains(DAY_NAMES[wd]).to_numpy() for wd in range(7)}
    hire, term = agents["hire_date"].to_numpy(), agents["termination_date"].to_numpy()
    enabled_date = agents["tool_enabled_date"].to_numpy()
    agent_factor = (np.where(agents["team"].isin(cfg.LAGGING_TEAMS), cfg.LAGGING_TEAM_FACTOR, 1.0)
                    * agents["_propensity"].to_numpy())

    s = cfg.TALK_SEC_SIGMA
    talk_mu = {p: np.log(m) - s * s / 2 for p, m in cfg.TALK_SEC_MEAN.items()}
    wait = cfg.NATIVE_WAIT_SEC

    agent_idx = np.full(n, -1)
    start_sec = np.zeros(n)
    talk, hold = np.zeros(n, int), np.zeros(n, int)
    path = np.full(n, "", dtype=object)
    reason = np.full(n, None, dtype=object)
    has_session = np.zeros(n, bool)

    arr_sec = arrivals["arrival_sec"].to_numpy()
    call_lang = arrivals["caller_language"].to_numpy()
    for d, idx in arrivals.groupby("call_date").indices.items():
        present = (works[d.weekday()] & (hire <= d)
                   & np.array([x is None or d < x for x in term]))
        floor = _Floor(present, shift_start, shift_end, lunch_start, lunch_end)
        days_on = np.array([(d - e).days if e is not None and d >= e else -1
                            for e in enabled_date])
        p_base = np.where(days_on >= 0,
                          agent_factor * (1 - np.exp(-np.maximum(days_on, 0) / cfg.RAMP_TAU_DAYS)), 0)

        for i in idx:
            t, lang = float(arr_sec[i]), call_lang[i]
            in_scope = lang in native_mask
            a = None
            if in_scope:
                pool = native_mask[lang]
                a = floor.pick(t, pool)
                if a is None and wait > 0:
                    tn = floor.next_free(t, pool)
                    if tn <= t + wait:
                        t, a = tn, floor.pick(tn, pool)
                    else:
                        t += wait
            if a is None:
                a = floor.pick(t, all_pool)
            while a is None:  # everyone busy: queue for the next free agent
                t = floor.next_free(t, all_pool)
                if t == np.inf:
                    break
                a = floor.pick(t, all_pool)
            if a is None:
                continue  # abandoned: nobody left on shift today

            native_call = in_scope and native_mask[lang][a]
            if not in_scope or native_call:
                p = "native"
            elif u_tool[i] < min(0.98, cfg.ADOPTION_TARGET[lang] * p_base[a]):
                p = "translation_tool"
            elif u_interp[i] < cfg.INTERPRETER_SHARE_OF_NON_TOOL:
                p = "interpreter_line"
            else:
                p = "no_support"
            if in_scope:
                reason[i] = "native" if native_call else "overflow"
            has_session[i] = p == "translation_tool" or (
                native_call and days_on[a] >= 0 and u_opt[i] < cfg.NATIVE_OPTIONAL_USE_RATE)

            talk[i] = round(np.exp(talk_mu[p] + s * z_talk[i]))
            hold[i] = round(cfg.HOLD_SEC_MEAN[p] * e_hold[i])
            if p == "interpreter_line":
                hold[i] += cfg.INTERPRETER_CONNECT_HOLD_SEC
            agent_idx[i], start_sec[i], path[i] = a, t, p
            floor.free_at[a] = t + talk[i] + hold[i] + wrap[i]

    routed = agent_idx >= 0
    calls = arrivals.assign(
        agent_id=np.where(routed, ids[np.maximum(agent_idx, 0)], None), start_sec=start_sec,
        talk_sec=talk, hold_sec=hold, handle_sec=talk + hold + wrap, routing_reason=reason,
        _path=path, _has_session=has_session)[routed].reset_index(drop=True)
    calls = _finish_calls(rng, calls, agents)
    calls.attrs["abandoned"] = int((~routed).sum())
    return calls


def _finish_calls(rng: np.random.Generator, calls: pd.DataFrame,
                  agents: pd.DataFrame) -> pd.DataFrame:
    """Timestamps, queue, transfers, disposition, CSAT and call ids."""
    n = len(calls)
    day = pd.to_datetime(calls["call_date"])
    calls["call_start_ts"] = day + pd.to_timedelta(calls["start_sec"].round(), unit="s")
    calls["call_end_ts"] = calls["call_start_ts"] + pd.to_timedelta(
        calls["talk_sec"] + calls["hold_sec"], unit="s")
    calls["queue"] = rng.choice(cfg.QUEUES, size=n, p=cfg.QUEUE_WEIGHTS)
    path = calls["_path"]
    calls["transferred"] = rng.random(n) < path.map(cfg.TRANSFER_RATE).to_numpy()
    calls["disposition"] = np.where(
        calls["transferred"], "Transferred",
        rng.choice(cfg.DISPOSITIONS, size=n, p=cfg.DISPOSITION_WEIGHTS))
    csat = np.clip(np.round(rng.normal(path.map(cfg.CSAT_MEAN).to_numpy(), 0.9)), 1, 5)
    calls["csat"] = pd.array(np.where(rng.random(n) < cfg.CSAT_RESPONSE_RATE, csat, np.nan),
                             dtype="Int64")

    calls = calls.join(agents.set_index("agent_id")[["team", "tool_enabled_date"]], on="agent_id")
    calls = calls.sort_values(["call_start_ts", "agent_id"]).reset_index(drop=True)
    calls["call_id"] = [f"C{i + 1:07d}" for i in range(n)]
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

    # Orphans: practice sessions after an agent's last call of the day. Any of
    # the agent's working days, so some fall before their tool_enabled_date.
    n_orphan = int(n * cfg.ORPHAN_SESSION_SHARE)
    last = calls.groupby(["agent_id", calls["call_start_ts"].dt.date])["call_end_ts"].max()
    tool_agents = set(c["agent_id"])
    last = last[last.index.get_level_values(0).isin(tool_agents)]
    pick = last.sample(n_orphan, random_state=int(rng.integers(1e9)))
    o_start = pick.to_numpy() + pd.to_timedelta(rng.uniform(600, 3600, n_orphan), unit="s").to_numpy()
    orphans = pd.DataFrame({
        "agent_id": pick.index.get_level_values(0),
        "call_id": None,
        "session_start_ts": o_start,
        "session_end_ts": o_start + pd.to_timedelta(rng.uniform(60, 600, n_orphan), unit="s").to_numpy(),
        "source_language": rng.choice(cfg.IN_SCOPE_LANGUAGES, n_orphan),
    })
    sessions = pd.concat([sessions, orphans], ignore_index=True)
    sessions = sessions.sort_values(["session_start_ts", "agent_id"]).reset_index(drop=True)

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
    """One vendor record per interpreter-line call; billed minutes round up."""
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


def generate() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Build all tables in memory. Returns (tables, calls with internal columns)."""
    rng = np.random.default_rng(cfg.SEED)
    Faker.seed(cfg.SEED)
    fake = Faker("en_US")

    agents = build_agents(rng, fake)
    prof = build_proficiency(rng, agents)
    agents = add_schedules(rng, agents)
    natives = prof[prof["proficiency_level"] == "native"]
    calls = route_calls(rng, build_arrivals(rng), agents,
                        set(zip(natives["agent_id"], natives["language"])))
    sessions = build_sessions(rng, calls)
    interp = build_interpreter(rng, calls)

    tables = {
        "dim_agent": agents.drop(columns=["_propensity"]),
        "dim_team": build_teams(agents),
        "agent_language_proficiency": prof,
        "fact_call": calls[CALL_COLS],
        "fact_translation_session": sessions,
        "fact_interpreter_usage": interp,
    }
    return tables, calls


def main() -> None:
    tables, calls = generate()
    out = Path(__file__).resolve().parents[1] / cfg.RAW_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False, compression="zstd")
        print(f"{name:28s} {len(df):>8,} rows")
    print(f"Abandoned calls (no agent left on shift): {calls.attrs['abandoned']}")

    print("\nChecks:")
    failed = 0
    for name, ok, detail in checks.run_all(tables):
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}")
    if failed:
        sys.exit(f"{failed} check(s) failed")


if __name__ == "__main__":
    main()
