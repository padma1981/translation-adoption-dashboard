-- Interpreter vendor rows whose call_id has no matching call.
create or replace view v_dq_orphan_interpreter as
select i.*
from fact_interpreter_usage i
left join fact_call c on c.call_id = i.call_id
where c.call_id is null;
