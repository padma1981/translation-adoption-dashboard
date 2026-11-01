-- Routing mix for in-scope language calls per day x agent x language.
create or replace view v_routing_daily as
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
    count(*) as in_scope_calls,
    count(*) filter (where routing_reason = 'native') as native_routed_calls,
    count(*) filter (where routing_reason = 'overflow') as overflow_calls,
    count(*) filter (where is_native_for_language) as native_handled_calls,
    count(*) filter (where eligible) as eligible_calls
from v_call_enriched
where is_in_scope
group by all;
