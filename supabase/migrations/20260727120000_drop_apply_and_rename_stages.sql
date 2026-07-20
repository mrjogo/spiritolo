-- Apply teardown + stage rename (Phase 1).
--
-- 1. Rip out the no-op apply/hold feature. Every stage writes its content to the
--    live tables during processing, so "apply" was only a state flip with no
--    deferred write to replay — dead weight that implied a gate that never
--    existed. Application is always immediate now. (The audit log remains the
--    substrate for a future rollback; rollback itself is not built.)
--      - drop `jobs.apply_mode`
--      - remove `pending_apply` from the `job_items.state` CHECK
--      - drop `apply_run_items()`
--      - recreate `create_run` without the `apply_mode` arg
--      - recreate the `runs` view without the `apply_mode` column (it depends on
--        the dropped column, so the column can't drop until the view stops
--        selecting it)
--
-- 2. Rename the six pipeline stages to canonical `<verb>-<object>` names in every
--    stored `stage` string:
--      extract -> extract-recipe   parse   -> parse-ingredients
--      map     -> map-ingredient   convert -> convert-steps
--      cluster -> cluster-recipes  export  -> export-recipegf
--
-- Existing migrations are immutable history; this is a new forward migration.

-- ---------------------------------------------------------------------------
-- 1. Apply teardown.
-- ---------------------------------------------------------------------------

-- 1a. The `runs` view selects `j.apply_mode`; recreate it without that column
--     first so the column drop below has no dependents. (create-or-replace can't
--     drop a column mid-list, so drop + recreate.)
drop view if exists public.runs;

-- 1b. Drop the no-op bulk-apply RPC and the apply_mode column.
drop function if exists public.apply_run_items(bigint, bigint[]);
alter table public.jobs drop column apply_mode;

-- 1c. Rewrite the job_items.state CHECK to drop the `pending_apply` value. Any
--     existing held rows collapse to `applied` (application is immediate now),
--     which also lets the tighter CHECK take without a violation.
update public.job_items set state = 'applied' where state = 'pending_apply';
alter table public.job_items
  drop constraint job_items_state_check,
  add constraint job_items_state_check
    check (state in ('pending', 'running', 'applied', 'flagged', 'failed'));

-- 1d. Recreate create_run without the apply_mode parameter/insert column. The
--     old two-arg overload is dropped explicitly (a different signature would
--     otherwise leave it in place alongside the new one).
drop function if exists public.create_run(text, text);

create or replace function public.create_run(stage text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  insert into public.jobs (stage, kind, state, created_by)
  values (stage, 'run', 'draft'::public.job_state, auth.uid())
  returning id into v_id;
  return v_id;
end;
$$;

revoke all on function public.create_run(text) from public;
grant execute on function public.create_run(text) to authenticated;

-- 1e. Recreate the `runs` read view minus `apply_mode` (otherwise unchanged).
create or replace view public.runs with (security_invoker = true) as
select
  j.id,
  j.stage,
  case j.state when 'succeeded' then 'done' else j.state::text end as state,
  j.llm_provider,
  j.llm_model,
  coalesce(c.task_count, 0)     as task_count,
  coalesce(c.flagged_count, 0)  as flagged_count,
  coalesce(c.never_run_count, 0) as never_run_count,
  coalesce(c.failed_count, 0)   as failed_count,
  j.cost_estimate_cents,
  j.max_cost_cents,
  j.created_at,
  j.created_by
from public.jobs j
left join lateral (
  select
    count(*) as task_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'flagged')   as flagged_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'never_run') as never_run_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'failed')    as failed_count
  from public.job_items i
  where i.job_id = j.id
) c on true;

grant select on public.runs to authenticated;

-- ---------------------------------------------------------------------------
-- 2. Recreate functions that dispatch on a hard-coded stage literal, so they
--    match the renamed data. `_eligible_base` / `add_run_items_by_filter` branch
--    the entity universe on the extract stage; `apply_review` dispatches its
--    write per stage; the taxonomy delete-guards count open `map` form proposals.
--    Also drop the now-invalid `pending_apply` value from the state IN-lists.
-- ---------------------------------------------------------------------------

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
    where p_stage <> 'extract-recipe'
    union all
    select p.id, p.url, p.site
    from public.pages p
    where p_stage = 'extract-recipe'
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

create or replace function public.add_run_items(
  job_id bigint, entity_type text, entity_ids bigint[]
) returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_stage text;
  v_count int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select stage into v_stage from public.jobs where id = add_run_items.job_id;
  if v_stage is null then
    raise exception 'run % not found', add_run_items.job_id using errcode = '23503';
  end if;

  with latest as (
    select distinct on (i.entity_id) i.entity_id, i.state as status
    from public.job_items i
    where i.stage = v_stage
      and i.state in ('applied', 'flagged', 'failed')
    order by i.entity_id, i.id desc
  ),
  ins as (
    insert into public.job_items (
      entity_type, entity_id, stage, code_version, outcome, method, state,
      job_id, outcome_payload
    )
    select add_run_items.entity_type, e.id, v_stage, '', 'pending', 'deterministic',
           'pending', add_run_items.job_id,
           jsonb_build_object('why_added', coalesce(l.status, 'never_run'))
    from unnest(add_run_items.entity_ids) as e(id)
    left join latest l on l.entity_id = e.id
    where not exists (
      select 1 from public.job_items m
      where m.job_id = add_run_items.job_id and m.entity_id = e.id and m.stage = v_stage
    )
    returning 1
  )
  select count(*)::int into v_count from ins;
  return v_count;
end;
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
  v_etype := case when v_stage = 'extract-recipe' then 'page' else 'recipe' end;

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

-- apply_review dispatches its per-stage write on the (now renamed) stage string.
create or replace function apply_review(p_id bigint) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  r human_reviews;
begin
  select * into r from human_reviews where id = p_id and state = 'resolved';
  if not found then
    return;
  end if;

  if r.stage = 'map-ingredient' then
    update ingredient_resolutions
       set taxonomy_slug = r.payload->>'slug', method = 'manual', updated_at = now()
     where normalized_name = r.entity_id;
    if not found then
      insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version)
      values (r.entity_id, r.payload->>'slug', 'manual', 'override');
    end if;

  elsif r.stage = 'parse-ingredients' then
    update recipe_ingredients set
        name       = coalesce(r.payload->>'name', name),
        amount     = coalesce((r.payload->>'amount')::numeric, amount),
        amount_max = coalesce((r.payload->>'amount_max')::numeric, amount_max),
        unit       = coalesce(r.payload->>'unit', unit)
     where recipe_id = split_part(r.entity_id, ':', 1)::bigint
       and position  = split_part(r.entity_id, ':', 2)::int;

  elsif r.stage = 'cluster-recipes' then
    update recipes set
        cluster_id     = coalesce(r.payload->>'cluster_id', cluster_id),
        variant_key    = coalesce(r.payload->>'variant_key', variant_key),
        canonical_name = coalesce(r.payload->>'canonical_name', canonical_name)
     where id = r.entity_id::bigint;

  elsif r.stage = 'extract-recipe' then
    update recipes set
        title     = coalesce(r.payload->>'title', title),
        author    = coalesce(r.payload->>'author', author),
        image_url = coalesce(r.payload->>'image_url', image_url)
     where id = r.entity_id::bigint;

  elsif r.stage = 'convert-steps' then
    delete from recipe_steps where recipe_id = r.entity_id::bigint;
    insert into recipe_steps (recipe_id, step_index, verb, roles, result, modifiers)
    select r.entity_id::bigint,
           (t.ordinality - 1)::int,
           t.e->>'verb',
           coalesce(t.e->'roles', '{}'::jsonb),
           t.e->>'result',
           coalesce(
             (select array_agg(x) from jsonb_array_elements_text(t.e->'modifiers') x),
             '{}'::text[]
           )
    from jsonb_array_elements(r.payload->'steps') with ordinality as t(e, ordinality);
  end if;
end;
$$;

-- The taxonomy delete-guards count open map-stage form proposals whose parent is
-- the node being deleted; the stage filter follows the rename.
create or replace function public.get_taxonomy_node_blockers(p_id bigint)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  return jsonb_build_object(
    'children', (
      select count(*)::int from public.taxonomy_edges where parent_id = p_id
    ),
    'child_names', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object('id', n.id, 'display_name', n.display_name)
          order by n.display_name
        )
        from public.taxonomy_edges e
        join public.taxonomy_nodes n on n.id = e.child_id
        where e.parent_id = p_id
      ),
      '[]'::jsonb
    ),
    'parents', (
      select count(*)::int from public.taxonomy_edges where child_id = p_id
    ),
    'aliases', (
      select count(*)::int from public.taxonomy_aliases where node_id = p_id
    ),
    'provenance', (
      select count(*)::int from public.taxonomy_provenance where node_id = p_id
    ),
    'recipe_ingredients', (
      select count(*)::int
      from public.recipe_ingredients ri
      join public.ingredient_resolutions ir
        on lower(btrim(ri.name)) = ir.normalized_name
      join public.taxonomy_nodes n on n.slug = ir.taxonomy_slug
      where n.id = p_id
    ),
    'form_proposals', (
      select count(*)::int from public.human_reviews
      where stage = 'map-ingredient' and origin = 'machine_proposal' and state = 'open'
        and payload->>'proposed_parent_id' = p_id::text
    )
  );
end;
$$;

create or replace function public.delete_taxonomy_node(p_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_children    int;
  v_recipes     int;
  v_proposals   int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  select count(*) into v_children
    from public.taxonomy_edges where parent_id = p_id;
  select count(*) into v_recipes
    from public.recipe_ingredients ri
    join public.ingredient_resolutions ir
      on lower(btrim(ri.name)) = ir.normalized_name
    join public.taxonomy_nodes n on n.slug = ir.taxonomy_slug
    where n.id = p_id;
  select count(*) into v_proposals
    from public.human_reviews
    where stage = 'map-ingredient' and origin = 'machine_proposal' and state = 'open'
      and payload->>'proposed_parent_id' = p_id::text;

  if v_children > 0 or v_recipes > 0 or v_proposals > 0 then
    raise exception
      'blocked: % children, % recipe references, % form proposal references',
      v_children, v_recipes, v_proposals
      using errcode = '23503',
            detail = jsonb_build_object(
              'children', v_children,
              'recipe_ingredients', v_recipes,
              'form_proposals', v_proposals
            )::text;
  end if;

  delete from public.taxonomy_nodes where id = p_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. Stage rename — rewrite stored `stage` strings old -> canonical.
-- ---------------------------------------------------------------------------
-- The tables that carry a stored `stage` string are `jobs`, `job_items`, and
-- `human_reviews`. (The version-as-queue tables `stage_live_version` /
-- `review_floors` that also had a `stage` column were folded away in
-- 20260726090000_explicit_runs.sql, so they are not present here.)

do $$
declare
  t text;
begin
  foreach t in array array['jobs', 'job_items', 'human_reviews']
  loop
    execute format($fmt$
      update public.%I set stage = case stage
        when 'extract' then 'extract-recipe'
        when 'parse'   then 'parse-ingredients'
        when 'map'     then 'map-ingredient'
        when 'convert' then 'convert-steps'
        when 'cluster' then 'cluster-recipes'
        when 'export'  then 'export-recipegf'
        else stage
      end
      where stage in ('extract','parse','map','convert','cluster','export')
    $fmt$, t);
  end loop;
end $$;
