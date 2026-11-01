-- Language-record coverage per agent x in-scope language.
create or replace view v_dq_agent_language as
select
    al.agent_id,
    a.agent_name,
    a.team,
    a.supervisor,
    a.site,
    a.hire_date,
    a.termination_date,
    al.language,
    al.has_record
from v_agent_language al
join v_agent a on a.agent_id = al.agent_id;
