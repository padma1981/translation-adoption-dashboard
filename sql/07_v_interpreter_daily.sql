-- Interpreter usage per day x agent x language, split by whether the agent
-- had the tool enabled ("interpreter used where tool was available").
create or replace view v_interpreter_daily as
select
    call_date as day,
    cast(date_trunc('week', call_date) as date) as week_start,
    cast(date_trunc('month', call_date) as date) as month_start,
    agent_id,
    agent_name,
    team,
    supervisor,
    site,
    caller_language as language,
    tool_enabled_on_call_date as tool_available,
    count(*) as interpreter_calls,
    sum(interpreter_minutes) as interpreter_minutes,
    sum(interpreter_cost_usd) as interpreter_spend_usd
from v_call_enriched
where has_interpreter
group by all;
