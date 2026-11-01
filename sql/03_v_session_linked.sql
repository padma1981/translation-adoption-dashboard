-- Session-to-call linking.
--   'call_id'     : the session logged its call_id
--   'time_window' : null call_id; matched to a call by the same agent. Strict
--                   containment first (session start within call start/end);
--                   only if no call contains it, a call within
--                   :link_tolerance_sec. If several calls match in the chosen
--                   tier, the closest call start wins and is_ambiguous is set.
--   'unlinked'    : no call found (e.g. practice sessions)
create or replace view v_session_linked as
with candidates as (
    select
        s.session_id,
        c.call_id,
        s.session_start_ts between c.call_start_ts and c.call_end_ts as within_call,
        abs(epoch(s.session_start_ts) - epoch(c.call_start_ts)) as start_gap_sec
    from fact_translation_session s
    join fact_call c
      on s.call_id is null
     and c.agent_id = s.agent_id
     and s.session_start_ts between c.call_start_ts - to_seconds(:link_tolerance_sec)
                                and c.call_end_ts + to_seconds(:link_tolerance_sec)
),
tiered as (
    select *, bool_or(within_call) over (partition by session_id) as any_within
    from candidates
),
ranked as (
    select *,
        count(*) over (partition by session_id) as n_candidates,
        row_number() over (partition by session_id order by start_gap_sec, call_id) as rn
    from tiered
    where within_call or not any_within
),
best as (
    select session_id, call_id, within_call, n_candidates from ranked where rn = 1
)
select
    s.session_id,
    s.agent_id,
    a.agent_name,
    a.team,
    a.supervisor,
    a.site,
    a.tool_enabled_date,
    s.call_id as logged_call_id,
    s.session_start_ts,
    s.session_end_ts,
    cast(s.session_start_ts as date) as session_date,
    s.source_language,
    s.target_language,
    s.error_flag,
    s.agent_rating,
    case when s.call_id is not null then 'call_id'
         when b.call_id is not null then 'time_window'
         else 'unlinked' end as link_method,
    coalesce(s.call_id, b.call_id) as linked_call_id,
    c.call_id is not null as linked_call_found,
    coalesce(b.n_candidates, 0) as n_candidates,
    coalesce(b.n_candidates, 0) > 1 as is_ambiguous,
    -- Rule 11: sessions before the agent's tool_enabled_date never count.
    a.tool_enabled_date is null
        or cast(s.session_start_ts as date) < a.tool_enabled_date as before_enablement,
    -- Rule 5: native speaker using the tool on a call in their native language.
    coalesce(al.is_native, false) as is_optional_use
from fact_translation_session s
left join best b on b.session_id = s.session_id
left join v_agent a on a.agent_id = s.agent_id
left join fact_call c on c.call_id = coalesce(s.call_id, b.call_id)
left join v_agent_language al on al.agent_id = c.agent_id and al.language = c.caller_language;
