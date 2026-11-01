"""Tunable assumptions for the synthetic data generator.

Every number that shapes the demo data lives here so it can be adjusted
without touching generator logic. All data is synthetic.
"""

from datetime import date

# --- Reproducibility -------------------------------------------------------
SEED = 20260401

# --- Date range ------------------------------------------------------------
START_DATE = date(2026, 4, 1)
END_DATE = date(2026, 9, 30)

# --- Languages -------------------------------------------------------------
IN_SCOPE_LANGUAGES = ["Spanish", "Portuguese", "Mandarin", "Vietnamese"]
AGENT_LANGUAGE = "English"  # language the agent speaks; tool target language

# Share of call volume by caller language (must sum to 1.0)
LANGUAGE_MIX = {
    "English": 0.80,
    "Spanish": 0.12,
    "Portuguese": 0.03,
    "Mandarin": 0.025,
    "Vietnamese": 0.025,
}

# --- Agents, teams, sites --------------------------------------------------
N_AGENTS = 150
SITES = ["Denver", "Charlotte"]
# team -> site; supervisors are generated one per team
TEAMS = {
    "Atlas": "Denver",
    "Beacon": "Denver",
    "Cascade": "Denver",
    "Delta": "Charlotte",
    "Echo": "Charlotte",
    "Summit": "Charlotte",
}
TERMINATED_SHARE = 0.08      # agents who leave during the date range
MID_RANGE_HIRE_SHARE = 0.08  # agents hired after START_DATE

# Native speakers are rare (~5% of agents). Each tuple is one agent and the
# language(s) they are native in. Guarantees >=1 native per in-scope
# language and one agent native in two languages.
NATIVE_AGENT_PLAN = [
    ("Spanish",),
    ("Spanish",),
    ("Spanish", "Portuguese"),
    ("Portuguese",),
    ("Mandarin",),
    ("Mandarin",),
    ("Vietnamese",),
]

# Non-native proficiency for in-scope languages (per agent x language).
# Probabilities for fluent / conversational / none; remainder of each agent's
# languages get no record at all some of the time (treated as "none").
NON_NATIVE_PROFICIENCY = {
    "Spanish": {"fluent": 0.06, "conversational": 0.14, "none": 0.80},
    "Portuguese": {"fluent": 0.02, "conversational": 0.05, "none": 0.93},
    "Mandarin": {"fluent": 0.01, "conversational": 0.02, "none": 0.97},
    "Vietnamese": {"fluent": 0.01, "conversational": 0.02, "none": 0.97},
}
MISSING_PROFICIENCY_SHARE = 0.10  # agents with no proficiency records at all

# --- Tool rollout ----------------------------------------------------------
# Phased by team. Agents hired later are enabled on their hire date.
TEAM_ROLLOUT_DATES = {
    "Atlas": date(2026, 5, 1),
    "Delta": date(2026, 5, 15),
    "Beacon": date(2026, 6, 1),
    "Echo": date(2026, 6, 15),
    "Cascade": date(2026, 7, 1),
    "Summit": date(2026, 7, 15),
}

# --- Agent schedules -------------------------------------------------------
# Each agent works 5 days a week with 2 consecutive days off. Weights favour
# weekends off, which matches the lower weekend volume.
DAYS_OFF_OPTIONS = {  # days-off pair -> share of agents
    ("Sat", "Sun"): 0.45,
    ("Sun", "Mon"): 0.15,
    ("Fri", "Sat"): 0.15,
    ("Mon", "Tue"): 0.10,
    ("Tue", "Wed"): 0.05,
    ("Wed", "Thu"): 0.05,
    ("Thu", "Fri"): 0.05,
}
SHIFT_HOURS = 8                        # includes the lunch break
SHIFT_START_RANGE = ("07:00", "11:00")  # staggered, in SHIFT_START_STEP_MIN steps
SHIFT_START_STEP_MIN = 30
LUNCH_MIN = 30
LUNCH_OFFSET_RANGE_MIN = (210, 270)    # lunch starts this long after shift start

# --- Call volume and routing -----------------------------------------------
CALLS_PER_DAY = 1500         # weekday volume
WEEKEND_VOLUME_FACTOR = 0.4  # Saturday/Sunday volume = CALLS_PER_DAY * factor
# Share of daily arrivals by hour of day (08:00-19:00). Morning and
# early-afternoon peaks, quieter late afternoon. Must sum to 1.0.
INTRADAY_ARRIVAL_WEIGHTS = {
    8: 0.07, 9: 0.10, 10: 0.12, 11: 0.11, 12: 0.09, 13: 0.11,
    14: 0.11, 15: 0.09, 16: 0.08, 17: 0.07, 18: 0.05,
}
QUEUES = ["Billing", "Technical Support", "Account Services", "Sales"]
QUEUE_WEIGHTS = [0.35, 0.30, 0.25, 0.10]

# Routing (simulated in arrival order): an in-scope language call goes to a
# free, on-shift agent native in that language (longest idle first). If none
# frees up within NATIVE_WAIT_SEC it overflows to any free, on-shift agent.
NATIVE_WAIT_SEC = 0

# --- Adoption --------------------------------------------------------------
# Steady-state tool adoption on eligible calls after rollout.
ADOPTION_TARGET = {
    "Spanish": 0.85,
    "Portuguese": 0.85,
    "Mandarin": 0.65,
    "Vietnamese": 0.65,
}
LAGGING_TEAMS = ["Cascade", "Echo"]
LAGGING_TEAM_FACTOR = 0.47      # 0.85 * 0.47 ~= 0.40
RAMP_TAU_DAYS = 21              # adoption ~= target * (1 - exp(-days / tau))
AGENT_PROPENSITY_BETA = (8, 2)  # per-agent multiplier, rescaled to mean 1.0

# Native speakers occasionally use the tool on their own language
# ("optional use"); never counted for or against adoption.
NATIVE_OPTIONAL_USE_RATE = 0.05

# Eligible calls without the tool
INTERPRETER_SHARE_OF_NON_TOOL = 0.70  # remainder is no_support

# --- Interpreter -----------------------------------------------------------
INTERPRETER_COST_PER_MIN = 1.75
INTERPRETER_VENDORS = ["BridgeVoice Interpreting", "ClearSpeak Partners"]
INTERPRETER_VENDOR_WEIGHTS = [0.6, 0.4]

# --- Call handling (seconds) -----------------------------------------------
# Talk time is lognormal around these means by handling path.
TALK_SEC_MEAN = {
    "native": 360,            # native agent or English call
    "translation_tool": 450,
    "interpreter_line": 600,
    "no_support": 480,
}
TALK_SEC_SIGMA = 0.35
HOLD_SEC_MEAN = {            # exponential, added to any connect hold below
    "native": 30,
    "translation_tool": 45,
    "interpreter_line": 90,
    "no_support": 90,
}
INTERPRETER_CONNECT_HOLD_SEC = 30  # minimum hold while the interpreter joins
WRAP_SEC_RANGE = (30, 90)     # after-call work (inclusive), in handle_sec only;
                              # the agent is not routable during wrap-up
TRANSFER_RATE = {
    "native": 0.04,
    "translation_tool": 0.06,
    "interpreter_line": 0.08,
    "no_support": 0.30,
}
CSAT_RESPONSE_RATE = 0.30
CSAT_MEAN = {
    "native": 4.4,
    "translation_tool": 4.1,
    "interpreter_line": 3.8,
    "no_support": 2.9,
}
DISPOSITIONS = ["Resolved", "Follow-up required", "Escalated"]
DISPOSITION_WEIGHTS = [0.80, 0.14, 0.06]

# --- Translation sessions --------------------------------------------------
SESSION_ERROR_RATE = 0.03
SESSION_ERROR_RATE_BY_LANGUAGE = {"Vietnamese": 0.07}
SESSION_NULL_CALL_ID_SHARE = 0.10  # logging gap; linked later by time window
ORPHAN_SESSION_SHARE = 0.01        # sessions outside any call (cannot link)
AGENT_RATING_RESPONSE_RATE = 0.40

# --- Output ----------------------------------------------------------------
RAW_DATA_DIR = "data/raw"
