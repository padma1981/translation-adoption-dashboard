-- Handle time, hold, transfers and CSAT per day x agent x language x segment.
-- segment = handling_path for eligible calls, else 'native_exempt' or 'english'.
create or replace view v_operational_daily as
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
    coalesce(handling_path, call_category) as segment,
    count(*) as calls,
    sum(talk_sec) as talk_sec,
    sum(hold_sec) as hold_sec,
    sum(handle_sec) as handle_sec,
    count(*) filter (where transferred) as transferred_calls,
    count(csat) as csat_responses,
    sum(csat) as csat_sum
from v_call_enriched
group by all;
