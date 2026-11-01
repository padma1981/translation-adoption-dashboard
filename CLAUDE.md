# Translation Tool Adoption Dashboard (Demo)

## Goal
Build a demo dashboard that measures adoption of a live translation tool used by
contact center agents. All data is synthetic. No real customer or employee data.

## Stack
- Python 3.11+
- pandas, numpy, Faker for synthetic data
- DuckDB for the metric layer (SQL views over Parquet files)
- Streamlit + Plotly for the dashboard
- pytest for tests

## Project structure
```
translation-adoption-dashboard/
  CLAUDE.md
  requirements.txt
  config.py              # seed, date range, volumes, rates (all tunable)
  data_gen/generate.py   # writes Parquet files to data/raw/, then runs checks
  data_gen/checks.py     # data consistency checks (also run by pytest)
  data/raw/
  sql/                   # DuckDB view definitions for metrics
  src/metrics.py         # loads views, returns DataFrames for the app
  app/streamlit_app.py   # main page
  app/pages/             # additional dashboard pages
  tests/
```

## Languages in scope
Spanish, Portuguese, Mandarin, Vietnamese. English calls are out of scope for
adoption metrics.

## Core business rules (do not change without asking)
1. A call is **eligible** (agent is expected to use the tool) when:
   - caller_language is Spanish, Portuguese, Mandarin, or Vietnamese, AND
   - the handling agent is NOT a native speaker of that language.
2. **Only native speakers are exempt**, and only for their native language(s).
   Fluent, conversational, or no proficiency all count as expected to use the tool.
3. If an agent has no proficiency record for a language, treat it as "none".
4. An agent can be native in more than one language.
5. Tool use by a native speaker on a call in their native language is tracked
   separately as "optional use" and never counts for or against adoption.
6. Every eligible call gets exactly one **handling path**, in priority order
   translation_tool > interpreter_line > no_support:
   - `translation_tool`: a translation session is linked to the call
   - `interpreter_line`: no tool session, but an interpreter vendor record exists
   - `no_support`: neither (coaching gap)
7. Every eligible call has an **expected support**, based on the handling agent
   on the call date:
   - tool enabled (call date >= tool_enabled_date) -> `translation_tool`
   - not enabled, or tool_enabled_date blank -> `interpreter_line`
8. **Tool adoption** = tool-enabled eligible calls with path `translation_tool`
   / all tool-enabled eligible calls.
9. **Interpreter compliance** = not-enabled eligible calls with path
   `interpreter_line` / all not-enabled eligible calls.
10. **Supported rate** = eligible calls whose path equals their expected support
    / all eligible calls.
11. Tool sessions dated before the agent's tool_enabled_date never count toward
    adoption; they are reported on the Data Quality page.
12. **Estimated interpreter cost avoided** = per language: tool-supported calls
    x that language's pre-rollout interpreter share of eligible calls
    x that language's pre-rollout average interpreter minutes per call x $1.75.
    "Pre-rollout" = calls before the first team rollout (2026-05-01).
    Native "optional use" sessions and unlinked practice sessions are excluded.
13. Team/site filters use the agent's current team (team history isn't modeled;
    say so in a footnote). Ramp charts align agents by days since their own
    tool_enabled_date.

## Data model
- `dim_agent`: agent_id, agent_name, team, supervisor, site, hire_date,
  tool_enabled_date, status (active / terminated), termination_date (first day
  not worked; null if active), days_off (e.g. "Sat,Sun"), shift_start,
  shift_end, lunch_start (HH:MM)
- `dim_team`: team, supervisor, site, rollout_date
- `agent_language_proficiency`: agent_id, language, proficiency_level
  (native / fluent / conversational / none)
- `fact_call`: call_id, call_start_ts, call_end_ts, caller_language, queue,
  agent_id, routing_reason ('native' / 'overflow'; null for English calls),
  talk_sec, hold_sec, handle_sec, transferred (bool), disposition, csat (1-5,
  nullable). call_end_ts - call_start_ts = talk_sec + hold_sec; handle_sec
  adds wrap-up. transferred is TRUE exactly when disposition = 'Transferred'.
- `fact_translation_session`: session_id, agent_id, call_id (nullable),
  session_start_ts, session_end_ts, source_language, target_language,
  error_flag, agent_rating (1-5, nullable)
- `fact_interpreter_usage`: interpreter_call_id, call_id, vendor, minutes,
  cost_usd

### Session-to-call linking
About 10% of translation sessions have a null call_id (simulating a logging gap).
Link these by matching agent_id where the session start falls within the call's
start and end time (strict containment first). If a tolerance window is used and
more than one call matches, pick the call with the closest start time and show
the ambiguous count. Report how many sessions were linked each way, how many
could not be linked, and how many are dated before the agent's tool_enabled_date,
on the Data Quality page.

## Synthetic data assumptions (put all of these in config.py)
- Random seed fixed so data is reproducible
- Date range: 2026-04-01 to 2026-09-30
- Tool rollout: phased by team, starting 2026-05-01
- ~150 agents, 6 teams, 2 sites; native speakers are rare: ~5% of agents (7-8 of 150)
  are native in an in-scope language, with at least one native per in-scope language
  and at least one agent native in two languages
- Schedules: each agent works 5 days a week (2 consecutive days off, varied by
  agent, weighted toward weekends) on an 8-hour shift (including a 30-minute
  lunch) starting between 07:00 and 11:00. Agents are routable only on shift,
  outside lunch, and when not on a call or in wrap-up.
- ~1,500 calls per weekday, weekends x WEEKEND_VOLUME_FACTOR (0.4); arrivals
  between 08:00 and 19:00 on an intraday curve (morning and early-afternoon
  peaks, quieter late afternoon); language mix roughly English 80%, Spanish 12%,
  Portuguese 3%, Mandarin 2.5%, Vietnamese 2.5%
- Routing is simulated call by call in arrival order:
  - Spanish/Portuguese/Mandarin/Vietnamese calls go to a free, on-shift agent
    native in that language (longest idle first). If none is free within
    NATIVE_WAIT_SEC (default 0), the call overflows to any free, on-shift agent
    on any team (longest idle first), regardless of tool status.
  - English calls go to any free, on-shift agent; natives take English calls
    when idle.
  - If nobody is free, the call waits for the next agent to free up.
  - fact_call.routing_reason records 'native' or 'overflow'; overflow calls are
    exactly the eligible calls. There is no fixed native-routing rate: overflow
    comes from native agents being busy, at lunch, off shift or off that day.
- Agent behavior on eligible calls stays probabilistic: tool-enabled agents use
  the tool per the adoption ramp; otherwise interpreter line or no support.
  Not-enabled agents can only use the interpreter line or no support.
- Adoption ramps after each team's rollout: Spanish/Portuguese toward ~85%,
  Mandarin/Vietnamese toward ~65%; two teams lag at ~40%
- Of eligible calls without the tool: ~70% interpreter line, ~30% no support
- Interpreter cost ~$1.75/minute; interpreter calls have at least
  INTERPRETER_CONNECT_HOLD_SEC (30) of hold while the interpreter joins, and
  billed minutes never exceed talk + hold by more than 1 minute
- Handle time: native agent fastest, tool calls moderately longer,
  interpreter calls longest
- Translation session error rate ~3%, higher for Vietnamese

## Dashboard pages
1. **Overview**: eligible calls, tool adoption, interpreter compliance, supported
   rate, trend over time, handling path mix, interpreter cost avoided
2. **Agents & Teams**: adoption by team, supervisor, site; agent leaderboard and
   low adopters; ramp curve by days since each agent's tool_enabled_date;
   footnote that team history isn't modeled (current team is used)
3. **Languages**: volume and adoption by language; overflow rate to non-native agents
4. **Operational Impact**: handle time, hold, transfers, CSAT by handling path
5. **Cost**: interpreter minutes and spend over time; estimated cost avoided;
   interpreter calls by tool-enabled agents shown separately as
   "interpreter used where tool was available"
6. **Data Quality**: session linking stats (direct / time match / ambiguous /
   unlinked), sessions before tool_enabled_date, missing proficiency, orphan records
7. **Feedback**: form for dashboard users to suggest improvements (see below)

### Date filter and global filters
- Sidebar date range picker, defaulting to the full data range
- Quick presets: Last 7 days, Last 30 days, Last 90 days, Month to date,
  Since rollout, All time
- Validate that start date is not after end date; show a friendly message if
  the selection returns no data
- Also in the sidebar: team, site, language (multi-select, default all)
- Store filter selections in st.session_state so they carry across all pages
- Every metric, chart, and table must respect the active filters
- Show the active date range at the top of each page

### Feedback area
- A dedicated Feedback page, plus a small "Give feedback" expander at the
  bottom of every page that pre-fills which page the user was on
- Form fields (st.form):
  - name (optional), email (optional)
  - page (dropdown, pre-filled when opened from a page)
  - feedback type: Bug / Data looks wrong / New metric or chart request /
    Usability / Other
  - rating: 1-5 "How useful is this dashboard?"
  - comments (required, text area)
- On submit: save with a timestamp and the active filter selections (so I can
  reproduce what the user was looking at), show a thank-you message, clear the form
- Storage: Google Sheets (via st-gsheets-connection), accessed only through
  src/feedback.py (save_feedback, load_feedback). Local files do not persist on
  Streamlit Community Cloud, so feedback must live outside the app.
  - Credentials come from st.secrets (Google service account); never commit them
  - For local development, fall back to a local SQLite file at
    data/feedback/feedback.db when no Sheets secrets are configured
- Owner view on the Feedback page, protected by a simple password from
  st.secrets: table of all feedback, filters by type and page, average rating,
  count by type, and CSV download
- Keep data/feedback/ out of git (.gitignore)
- Tests: saving and loading a feedback record, required-field validation

## Deployment (Streamlit Community Cloud)
The app must be hosted in the cloud so it can be demoed from any device.
- Code lives in a GitHub repo; the app deploys from it on Streamlit Community Cloud
- Entry point: app/streamlit_app.py
- requirements.txt pins all versions; add .streamlit/config.toml for the theme
- Synthetic data: commit the generated Parquet files in data/raw/ (keep total
  size small, well under 50 MB) so the app starts fast and shows identical data
  every time. Load with @st.cache_data.
- Secrets (Google Sheets credentials, owner password) go in
  .streamlit/secrets.toml locally (git-ignored) and in the app's Secrets
  settings on Community Cloud. Provide a secrets.toml.example with placeholders.
- Make the app look good on a laptop and be usable on a tablet/phone
  (layout="wide", charts use container width, avoid very wide tables)
- Write a README.md with: what the demo shows, how to run locally, and
  step-by-step deployment and Google Sheets setup instructions
- No real data anywhere in the repo; the repo can be public

## Working conventions
- Build in phases and stop for review after each:
  1. Data generator  2. Metric views + tests  3. Dashboard pages with filters  4. Feedback page and storage
  5. Deployment prep (README, secrets example, size check)
- Business rules must have pytest tests (especially the native-speaker exemption
  and handling-path assignment).
- Keep metric logic in SQL views or src/metrics.py, never inside Streamlit pages.
- Use plain, readable code with short docstrings. No over-engineering.
