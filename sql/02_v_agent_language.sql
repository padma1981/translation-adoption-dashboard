-- Every agent x in-scope language. No record = 'none' (rule 3).
-- Only 'native' exempts, and only for that language (rule 2); an agent can be
-- native in several languages (rule 4).
create or replace view v_agent_language as
with languages as (
    select unnest([:in_scope_languages]) as language
),
records as (
    -- If an agent has several rows for a language, native wins, then the
    -- highest other level.
    select
        agent_id,
        language,
        arg_max(proficiency_level,
                case proficiency_level when 'native' then 4 when 'fluent' then 3
                     when 'conversational' then 2 else 1 end) as proficiency_level
    from agent_language_proficiency
    group by agent_id, language
)
select
    a.agent_id,
    l.language,
    coalesce(r.proficiency_level, 'none') as proficiency_level,
    r.agent_id is not null as has_record,
    coalesce(r.proficiency_level, 'none') = 'native' as is_native
from v_agent a
cross join languages l
left join records r on r.agent_id = a.agent_id and r.language = l.language;
