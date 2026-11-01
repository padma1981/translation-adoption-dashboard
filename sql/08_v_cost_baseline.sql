-- Pre-rollout interpreter baseline per language (rule 12).
-- Pre-rollout = eligible calls before the first team rollout date. This is a
-- fixed reference and is not affected by dashboard filters.
create or replace view v_cost_baseline as
with pre as (
    select *
    from v_call_enriched
    where eligible and call_date < (select min(rollout_date) from dim_team)
)
select
    caller_language as language,
    count(*) as pre_rollout_eligible_calls,
    count(*) filter (where has_interpreter) as pre_rollout_interpreter_calls,
    count(*) filter (where has_interpreter) / count(*) as interpreter_share,
    avg(interpreter_minutes) filter (where has_interpreter) as avg_interpreter_minutes,
    count(*) filter (where has_interpreter) / count(*)
        * avg(interpreter_minutes) filter (where has_interpreter)
        * :interpreter_cost_per_min as avoided_usd_per_tool_call
from pre
group by caller_language;
