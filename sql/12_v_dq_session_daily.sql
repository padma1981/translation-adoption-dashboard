-- Session data quality per day x agent x source language x link method.
create or replace view v_dq_session_daily as
select
    session_date as day,
    cast(date_trunc('week', session_date) as date) as week_start,
    cast(date_trunc('month', session_date) as date) as month_start,
    agent_id,
    agent_name,
    team,
    supervisor,
    site,
    source_language as language,
    link_method,
    count(*) as sessions,
    count(*) filter (where is_ambiguous) as ambiguous_sessions,
    count(*) filter (where before_enablement) as before_enablement_sessions,
    count(*) filter (where link_method = 'unlinked') as unlinked_practice_sessions,
    count(*) filter (where is_optional_use) as optional_use_sessions,
    count(*) filter (where link_method = 'call_id' and not linked_call_found) as call_id_not_found_sessions
from v_session_linked
group by all;
