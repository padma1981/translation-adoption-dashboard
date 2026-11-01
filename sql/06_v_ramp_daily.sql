-- Tool-enabled eligible calls aligned by days since each agent's own
-- tool_enabled_date (day 0 = enablement day).
create or replace view v_ramp_daily as
select
    day, week_start, month_start, agent_id, agent_name, team, supervisor, site, language,
    days_since_enabled,
    enabled_eligible_calls,
    enabled_tool_calls
from v_adoption_daily
where days_since_enabled is not null;
