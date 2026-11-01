-- Eligible-call counts per day x agent x language. Rates (rules 8-10) are
-- ratios of these sums, computed after filtering in src/metrics.py.
create or replace view v_adoption_daily as
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
    tool_enabled_date,
    days_since_enabled,
    count(*) as eligible_calls,
    count(*) filter (where expected_support = 'translation_tool') as enabled_eligible_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'translation_tool') as enabled_tool_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'interpreter_line') as enabled_interpreter_calls,
    count(*) filter (where expected_support = 'translation_tool'
                       and handling_path = 'no_support') as enabled_no_support_calls,
    count(*) filter (where expected_support = 'interpreter_line') as not_enabled_eligible_calls,
    count(*) filter (where expected_support = 'interpreter_line'
                       and handling_path = 'interpreter_line') as not_enabled_interpreter_calls,
    count(*) filter (where is_supported) as supported_calls,
    count(*) filter (where handling_path = 'translation_tool') as tool_calls,
    count(*) filter (where handling_path = 'interpreter_line') as interpreter_calls,
    count(*) filter (where handling_path = 'no_support') as no_support_calls
from v_call_enriched
where eligible
group by all;
