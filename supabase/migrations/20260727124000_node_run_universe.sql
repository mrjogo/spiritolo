-- Node run universe (Phase 4).
--
-- The two harmonization stages (`combine-nodes`, `connect-nodes`) operate on
-- taxonomy_node entities, not recipes/pages. Teach the run-assembly RPCs about
-- that third entity universe so an operator can browse + select the taxonomy
-- NODES a harmonization run targets in /ops.
--
--   - `_eligible_base` gains a third `universe` branch for the two node stages,
--     surfacing every taxonomy_node with its `status` mapped onto the `source`
--     column. That makes the existing "source" facet a live/provisional filter:
--     the operator keeps the provisional residue (default) or includes live
--     nodes to "run broadly". Node ids are bigint (like recipe ids) and
--     display_name/status are text, so the branch mirrors the recipe branch's
--     column types exactly and the per-stage `status` join is unchanged.
--   - `add_run_items_by_filter` picks `taxonomy_node` as the entity_type for the
--     two node stages (`taxonomy_node` was widened into the job_items
--     entity_type CHECK in 20260727123000).
--
-- Existing migrations are immutable history; this is a new forward migration.
-- Bodies are copied verbatim from 20260727120000 with only the universe branch /
-- v_etype changes noted above.

create or replace function public._eligible_base(p_stage text, p_filter jsonb)
returns table(
  entity_id bigint, title text, source text,
  status text, code_version text, last_run timestamptz
)
language sql
stable
set search_path = ''
as $$
  with universe as (
    select r.id as entity_id,
           coalesce(nullif(btrim(r.title), ''), r.source_url) as title,
           r.site as source
    from public.recipes r
    where p_stage not in ('extract-recipe', 'combine-nodes', 'connect-nodes')
    union all
    select p.id, p.url, p.site
    from public.pages p
    where p_stage = 'extract-recipe'
    union all
    select n.id as entity_id, n.display_name as title, n.status as source
    from public.taxonomy_nodes n
    where p_stage in ('combine-nodes', 'connect-nodes')
  ),
  latest as (
    select distinct on (i.entity_id)
           i.entity_id,
           i.state as status,
           i.code_version,
           coalesce(i.finished_at, i.started_at) as last_run
    from public.job_items i
    where i.stage = p_stage
      and i.state in ('applied', 'flagged', 'failed')
    order by i.entity_id, i.id desc
  ),
  joined as (
    select u.entity_id, u.title, u.source,
           coalesce(l.status, 'never_run') as status,
           coalesce(l.code_version, '') as code_version,
           l.last_run
    from universe u
    left join latest l on l.entity_id = u.entity_id
  )
  select entity_id, title, source, status, code_version, last_run
  from joined
  where (p_filter -> 'status' is null
         or status = any (array(select jsonb_array_elements_text(p_filter -> 'status'))))
    and (p_filter -> 'source' is null
         or source = any (array(select jsonb_array_elements_text(p_filter -> 'source'))))
    and (p_filter ->> 'code_version_before' is null
         or code_version < (p_filter ->> 'code_version_before'))
    and (p_filter ->> 'search' is null
         or title ilike '%' || (p_filter ->> 'search') || '%');
$$;

create or replace function public.add_run_items_by_filter(job_id bigint, p_filter jsonb)
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_stage text;
  v_etype text;
  v_count int;
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select stage into v_stage from public.jobs where id = add_run_items_by_filter.job_id;
  if v_stage is null then
    raise exception 'run % not found', add_run_items_by_filter.job_id using errcode = '23503';
  end if;
  v_etype := case
    when v_stage = 'extract-recipe' then 'page'
    when v_stage in ('combine-nodes', 'connect-nodes') then 'taxonomy_node'
    else 'recipe'
  end;

  with base as (
    select b.entity_id, b.status from public._eligible_base(v_stage, v_filter) b
  ),
  ins as (
    insert into public.job_items (
      entity_type, entity_id, stage, code_version, outcome, method, state,
      job_id, outcome_payload
    )
    select v_etype, base.entity_id, v_stage, '', 'pending', 'deterministic', 'pending',
           add_run_items_by_filter.job_id,
           jsonb_build_object('why_added', base.status)
    from base
    where not exists (
      select 1 from public.job_items m
      where m.job_id = add_run_items_by_filter.job_id
        and m.entity_id = base.entity_id and m.stage = v_stage
    )
    returning 1
  )
  select count(*)::int into v_count from ins;
  return v_count;
end;
$$;
