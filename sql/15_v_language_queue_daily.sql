-- In-scope language calls per day x agent x language x queue, with the
-- tool-enabled eligible calls by handling path (Overview language table).
create or replace view v_language_queue_daily as
select
    call_date as day,
    cast(date_trunc('month', call_date) as date) as month_start,
    agent_id,
    agent_name,
    team,
    supervisor,
    site,
    caller_language as language,
    queue,
    count(*) as language_calls,
    count(*) filter (where expected_support = 'translation_tool') as enabled_eligible_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'translation_tool') as enabled_tool_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'interpreter_line') as enabled_interpreter_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'no_support') as enabled_no_support_calls
from v_call_enriched
where is_in_scope
group by all;
