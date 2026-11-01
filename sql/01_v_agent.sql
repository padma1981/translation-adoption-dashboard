-- Agent dimension with the team's rollout date.
-- Team/site are the agent's current team; team history isn't modeled.
create or replace view v_agent as
select
    a.agent_id,
    a.agent_name,
    a.team,
    a.supervisor,
    a.site,
    a.hire_date,
    a.tool_enabled_date,
    a.status,
    a.termination_date,
    a.days_off,
    a.shift_start,
    a.shift_end,
    a.lunch_start,
    t.rollout_date as team_rollout_date
from dim_agent a
left join dim_team t on t.team = a.team;
