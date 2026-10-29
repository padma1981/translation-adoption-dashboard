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
  data_gen/generate.py   # writes Parquet files to data/raw/
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
6. Every eligible call gets exactly one **handling path**:
   - `translation_tool`: a translation session is linked to the call
   - `interpreter_line`: no tool session, but an interpreter vendor record exists
   - `no_support`: neither (coaching gap)
7. Adoption rate = eligible calls with path `translation_tool` / all eligible calls.

## Data model
- `dim_agent`: agent_id, agent_name, team, supervisor, site, hire_date,
  tool_enabled_date, status (active / terminated)
- `agent_language_proficiency`: agent_id, language, proficiency_level
  (native / fluent / conversational / none)
- `fact_call`: call_id, call_start_ts, call_end_ts, caller_language, queue,
  agent_id, talk_sec, hold_sec, handle_sec, transferred (bool), disposition,
  csat (1-5, nullable)
- `fact_translation_session`: session_id, agent_id, call_id (nullable),
  session_start_ts, session_end_ts, source_language, target_language,
  error_flag, agent_rating (1-5, nullable)
- `fact_interpreter_usage`: interpreter_call_id, call_id, vendor, minutes,
  cost_usd

### Session-to-call linking
About 10% of translation sessions have a null call_id (simulating a logging gap).
Link these by matching agent_id where the session start falls within the call's
start and end time. Report how many sessions were linked each way, and how many
could not be linked, on a data quality page.

## Synthetic data assumptions (put all of these in config.py)
- Random seed fixed so data is reproducible
- Date range: 2026-04-01 to 2026-09-30
- Tool rollout: phased by team, starting 2026-05-01
- ~150 agents, 6 teams, 2 sites; native speakers are rare: ~5% of agents (7-8 of 150)
  are native in an in-scope language, with at least one native per in-scope language
  and at least one agent native in two languages
- ~1,500 calls/day; language mix roughly English 80%, Spanish 12%,
  Portuguese 3%, Mandarin 2.5%, Vietnamese 2.5%
- Routing: only ~35% of in-scope language calls go to a native agent when one is
  available; the rest overflow to non-native agents (this creates eligible calls),
  so the large majority of non-English calls are eligible for the tool
- Adoption ramps after each team's rollout: Spanish/Portuguese toward ~85%,
  Mandarin/Vietnamese toward ~65%; two teams lag at ~40%
- Of eligible calls without the tool: ~70% interpreter line, ~30% no support
- Interpreter cost ~$1.75/minute
- Handle time: native agent fastest, tool calls moderately longer,
  interpreter calls longest
- Translation session error rate ~3%, higher for Vietnamese

## Dashboard pages
1. **Overview**: eligible calls, adoption rate, trend over time, handling path mix,
   interpreter cost avoided
2. **Agents & Teams**: adoption by team, supervisor, site; agent leaderboard and
   low adopters; ramp curve since enablement
3. **Languages**: volume and adoption by language; overflow rate to non-native agents
4. **Operational Impact**: handle time, hold, transfers, CSAT by handling path
5. **Cost**: interpreter minutes and spend over time; estimated cost avoided
6. **Data Quality**: session linking stats, missing proficiency, orphan records
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
