-- Estimated interpreter cost avoided per day x agent x language (rule 12):
-- tool-supported eligible calls x the language's avoided cost per tool call.
-- Native optional use is not eligible and unlinked practice sessions have no
-- call, so neither is counted.
create or replace view v_cost_avoided_daily as
select
    d.day, d.week_start, d.month_start, d.agent_id, d.agent_name, d.team, d.supervisor,
    d.site, d.language,
    d.tool_calls,
    d.tool_calls * coalesce(b.avoided_usd_per_tool_call, 0) as cost_avoided_usd
from v_adoption_daily d
left join v_cost_baseline b on b.language = d.language
where d.tool_calls > 0;
