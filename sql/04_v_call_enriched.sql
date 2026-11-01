-- One row per call with eligibility, expected support and handling path.
-- Business rules: CLAUDE.md "Core business rules".
create or replace view v_call_enriched as
with tool as (
    -- Countable tool sessions per call (rule 11 drops pre-enablement ones).
    select linked_call_id as call_id, count(*) as n_tool_sessions
    from v_session_linked
    where linked_call_id is not null and not before_enablement
    group by linked_call_id
),
interpreter as (
    select call_id, sum(minutes) as minutes, sum(cost_usd) as cost_usd
    from fact_interpreter_usage
    group by call_id
),
base as (
    select
        c.call_id,
        c.call_start_ts,
        c.call_end_ts,
        cast(c.call_start_ts as date) as call_date,
        c.caller_language,
        c.queue,
        c.agent_id,
        a.agent_name,
        a.team,
        a.supervisor,
        a.site,
        c.routing_reason,
        c.talk_sec,
        c.hold_sec,
        c.handle_sec,
        c.transferred,
        c.disposition,
        c.csat,
        a.tool_enabled_date,
        al.proficiency_level,
        coalesce(al.has_record, false) as has_proficiency_record,
        c.caller_language in (:in_scope_languages) as is_in_scope,
        coalesce(al.is_native, false) as is_native_for_language,
        a.tool_enabled_date is not null
            and cast(c.call_start_ts as date) >= a.tool_enabled_date as tool_enabled_on_call_date,
        coalesce(t.n_tool_sessions, 0) as n_tool_sessions,
        i.call_id is not null as has_interpreter,
        coalesce(i.minutes, 0) as interpreter_minutes,
        coalesce(i.cost_usd, 0) as interpreter_cost_usd
    from fact_call c
    left join v_agent a on a.agent_id = c.agent_id
    left join v_agent_language al on al.agent_id = c.agent_id and al.language = c.caller_language
    left join tool t on t.call_id = c.call_id
    left join interpreter i on i.call_id = c.call_id
),
flags as (
    select *,
        -- Rule 1: in-scope language and agent not native in it.
        is_in_scope and not is_native_for_language as eligible,
        n_tool_sessions > 0 as has_tool_session
    from base
),
paths as (
    select *,
        case when not is_in_scope then 'english'
             when is_native_for_language then 'native_exempt'
             else 'eligible' end as call_category,
        case when tool_enabled_on_call_date then call_date - tool_enabled_date end as days_since_enabled,
        -- Rule 5: tracked separately, never counts for or against adoption.
        is_native_for_language and has_tool_session as is_optional_use,
        -- Rule 6: translation_tool > interpreter_line > no_support.
        case when not eligible then null
             when has_tool_session then 'translation_tool'
             when has_interpreter then 'interpreter_line'
             else 'no_support' end as handling_path,
        -- Rule 7: expected support from the agent's enablement on the call date.
        case when not eligible then null
             when tool_enabled_on_call_date then 'translation_tool'
             else 'interpreter_line' end as expected_support
    from flags
)
select *,
    eligible and handling_path = expected_support as is_supported
from paths;
