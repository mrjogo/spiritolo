-- Explicit runs (2/2): the operator-assembled run model.
--
-- Replaces version-derived stage queues with runs the operator assembles
-- explicitly. A run is a `jobs` row (draft -> queued -> running -> done) that
-- owns explicit `job_items` (per-entity membership + outcome, renamed from
-- `stage_runs`); the worker processes a job's pending `job_items` instead of
-- re-deriving a NOT-EXISTS predicate. `human_reviews` is `stage_reviews` renamed
-- (the individual human-attention queue). The version-as-queue-driver apparatus
-- (`stage_live_version` / `stage_queue_versions` / `stage_config` /
-- `review_floors` / `job_batches`) is folded away.
--
-- Data migration: the only existing processing rows are cold-build output in
-- `stage_runs`. Carry them into `job_items` under one synthetic "done" backfill
-- job per stage, mapping outcome -> task state so the add-page status facets are
-- populated from day one and every parked item is selectable into a first real
-- (LLM) run — the exact workflow that motivated this redesign.
--
-- The two new job_state enum values ('draft'/'done') were added by the preceding
-- 20260726080000 migration so they're committed before first use here.

-- ---------------------------------------------------------------------------
-- 1. jobs — the run. New per-run columns; draft default; drop batching.
-- ---------------------------------------------------------------------------
alter table jobs
  add column llm_provider text,
  add column llm_model    text,
  add column apply_mode   text not null default 'auto'
    check (apply_mode in ('auto', 'hold'));

-- A freshly-created run starts as a draft (membership assembled, LLM tier
-- chosen) until Start. The legacy 'queued' default is superseded.
alter table jobs alter column state set default 'draft';

-- job_batches is folded away (no fan-out — one run = one explicit set). Drop the
-- FK column first so the table drop below has no dependents.
alter table jobs drop column batch_id;

-- ---------------------------------------------------------------------------
-- 2. stage_runs -> job_items — per-entity membership AND outcome.
-- ---------------------------------------------------------------------------
alter table stage_runs rename to job_items;

-- `version` is now an informational stamp of the code version that produced the
-- row (NOT a queue driver) — rename to say so.
alter table job_items rename column version to code_version;

-- The lifecycle state (intent when pending, outcome when terminal) + the held
-- would-be change for a pending_apply item.
alter table job_items
  add column state text not null default 'pending'
    check (state in ('pending', 'running', 'applied', 'pending_apply', 'flagged', 'failed')),
  add column outcome_payload jsonb;

-- batch_id folds away with job_batches; its FK drops with the column.
alter table job_items drop column batch_id;

-- Rename the carried-over indexes / constraints to the new table name.
alter index stage_runs_queue_idx rename to job_items_queue_idx;
alter index stage_runs_job_idx   rename to job_items_job_idx;
alter table job_items
  rename constraint stage_runs_entity_type_entity_id_stage_version_key
                 to job_items_entity_type_entity_id_stage_code_version_key;
-- job_items.job_id already carries a FK to jobs (added 20260719); rename it too.
alter table job_items
  rename constraint stage_runs_job_id_fkey to job_items_job_id_fkey;
alter policy stage_runs_admin_read on job_items rename to job_items_admin_read;

-- Membership FK index (the worker scans a job's pending items).
create index if not exists job_items_membership_idx
  on job_items (job_id, stage, state);

-- ---------------------------------------------------------------------------
-- 3. Backfill job_items.state from the cold-build outcome.
-- ---------------------------------------------------------------------------
-- resolved -> applied (content was written to live), failed -> failed, and
-- pending/abstain/proposes_new -> flagged (parked — no content written, needs
-- an LLM/human pass).
update job_items set state = case outcome
  when 'resolved' then 'applied'
  when 'failed'   then 'failed'
  else 'flagged'
end;

-- ---------------------------------------------------------------------------
-- 4. Synthetic backfill jobs own the migrated (job_id-less) items.
-- ---------------------------------------------------------------------------
-- One 'done' job per distinct stage among the orphaned rows, marked with a null
-- created_by (system). 'done' was never used before this migration, so these are
-- the only 'done'/null-created_by jobs — the attach UPDATE below is unambiguous.
insert into jobs (stage, state, kind, created_by)
select distinct stage, 'done'::job_state, 'run', null::uuid
from job_items
where job_id is null;

update job_items i set job_id = j.id
from jobs j
where i.job_id is null
  and j.state = 'done'
  and j.stage = i.stage
  and j.created_by is null;

-- ---------------------------------------------------------------------------
-- 5. stage_reviews -> human_reviews — the individual human-attention queue.
-- ---------------------------------------------------------------------------
alter table stage_reviews rename to human_reviews;
alter index stage_reviews_one_open   rename to human_reviews_one_open;
alter index stage_reviews_queue_idx  rename to human_reviews_queue_idx;
alter trigger audit_stage_reviews on human_reviews rename to audit_human_reviews;
alter policy stage_reviews_admin_read on human_reviews rename to human_reviews_admin_read;

-- Recreate the three review functions with `human_reviews` in their bodies
-- (plpgsql bodies are opaque text, so the table rename does not rewrite them).

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

  if r.stage = 'map' then
    update ingredient_resolutions
       set taxonomy_slug = r.payload->>'slug', method = 'manual', updated_at = now()
     where normalized_name = r.entity_id;
    if not found then
      insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version)
      values (r.entity_id, r.payload->>'slug', 'manual', 'override');
    end if;

  elsif r.stage = 'parse' then
    update recipe_ingredients set
        name       = coalesce(r.payload->>'name', name),
        amount     = coalesce((r.payload->>'amount')::numeric, amount),
        amount_max = coalesce((r.payload->>'amount_max')::numeric, amount_max),
        unit       = coalesce(r.payload->>'unit', unit)
     where recipe_id = split_part(r.entity_id, ':', 1)::bigint
       and position  = split_part(r.entity_id, ':', 2)::int;

  elsif r.stage = 'cluster' then
    update recipes set
        cluster_id     = coalesce(r.payload->>'cluster_id', cluster_id),
        variant_key    = coalesce(r.payload->>'variant_key', variant_key),
        canonical_name = coalesce(r.payload->>'canonical_name', canonical_name)
     where id = r.entity_id::bigint;

  elsif r.stage = 'extract' then
    update recipes set
        title     = coalesce(r.payload->>'title', title),
        author    = coalesce(r.payload->>'author', author),
        image_url = coalesce(r.payload->>'image_url', image_url)
     where id = r.entity_id::bigint;

  elsif r.stage = 'convert' then
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

create or replace function flag_review(
  p_entity_kind text,
  p_entity_id   text,
  p_stage       text,
  p_note        text default null
) returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id bigint;
begin
  if not public.is_admin() then
    raise exception 'not authorized';
  end if;
  insert into human_reviews (entity_kind, entity_id, stage, origin, note, created_by)
  values (p_entity_kind, p_entity_id, p_stage, 'human_flag', p_note, auth.uid()::text)
  on conflict (entity_kind, entity_id, stage) where state = 'open'
    do update set note = coalesce(excluded.note, human_reviews.note),
                  updated_at = now()
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function resolve_review(
  p_id      bigint,
  p_payload jsonb default null,
  p_dismiss boolean default false
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_admin() then
    raise exception 'not authorized';
  end if;
  if p_dismiss then
    update human_reviews
       set state = 'dismissed', reviewed_by = auth.uid()::text, reviewed_at = now()
     where id = p_id;
    return;
  end if;
  update human_reviews
     set state = 'resolved',
         payload = coalesce(p_payload, payload),
         reviewed_by = auth.uid()::text,
         reviewed_at = now()
   where id = p_id;
  perform apply_review(p_id);
end;
$$;

grant execute on function flag_review(text, text, text, text) to authenticated;
grant execute on function resolve_review(bigint, jsonb, boolean) to authenticated;

-- The taxonomy node-delete guards (20260725) count open map machine_proposals
-- whose proposed_parent is the node being deleted; they read the review table by
-- its old name, so recreate them against human_reviews.
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
      where stage = 'map' and origin = 'machine_proposal' and state = 'open'
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
    where stage = 'map' and origin = 'machine_proposal' and state = 'open'
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
-- 6. needs_review — the curator queue is now simply the open human_reviews rows.
-- ---------------------------------------------------------------------------
-- The old view unioned machine-couldn't-finish rows at the live version and
-- below-floor auto-resolves off `stage_runs` + `stage_live_version` + a
-- confidence floor — all folded away here. In the explicit-runs model a flagged
-- job_item raises a human_reviews row, and machine-residue surfacing moves to
-- the add-page status facets (RPC-computed). Recreate BEFORE dropping the folded
-- objects so nothing depends on them.
create or replace view needs_review
  with (security_invoker = true)
as
  select entity_kind, entity_id, stage, origin as reason
  from human_reviews
  where state = 'open';

grant select on needs_review to authenticated;

-- ---------------------------------------------------------------------------
-- 7. audit.log gains a nullable job_id back-link.
-- ---------------------------------------------------------------------------
alter table audit.log add column job_id bigint references public.jobs(id);

-- ---------------------------------------------------------------------------
-- 8. Drop the folded objects (after their data + dependents are handled).
-- ---------------------------------------------------------------------------
-- The dashboard/queue aggregates fed only the version-queue apparatus; facets
-- now come from RPCs (a later migration). Drop the views/functions first, then
-- the tables they read.
drop view if exists stage_run_outcome_counts;
drop function if exists stage_queue_counts();
drop function if exists floor_for(text);

drop table if exists stage_queue_versions cascade;
drop table if exists stage_live_version   cascade;
drop table if exists review_floors         cascade;
drop table if exists stage_config          cascade;
drop table if exists job_batches           cascade;
