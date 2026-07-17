-- Unified stage reviews: one human-in-the-loop layer for every pipeline stage.
--
-- Consolidates taxonomy_proposals, recipegf_proposals, and
-- ingredient_resolutions.method='manual' into ONE stage_reviews table where a
-- flag, a machine proposal, and a human override are the same row distinguished
-- by (state, origin). Human input lives here — a table the stage_fn never
-- writes — so a rerun or version bump cannot clobber it ("pin survives rerun").
--
-- Also makes stage_runs append-versioned (one row per version, not latest-only)
-- and adds a per-stage live pointer, so a future shadow-diff eval has its data
-- shape. Materialization of a resolved override into a stage's live output
-- table is the SQL function apply_review(), reachable from both the web RPCs
-- (no backend) and the worker's Python re-apply loop.
--
-- The backfill from the three sources + dropping the two proposal tables is a
-- SEPARATE later migration (…_stage_reviews_backfill.sql), so this one is purely
-- additive and safe to forward-apply on its own.

-- ---------------------------------------------------------------------------
-- 1. stage_reviews — the un-clobbered human/proposal layer.
-- ---------------------------------------------------------------------------
create table stage_reviews (
  id             bigserial primary key,
  entity_kind    text not null,   -- recipe_ingredient | ingredient_name | recipe_step | recipe | cluster | page
  entity_id      text not null,   -- text: holds bigint ids AND name-keys (ingredient_name = normalized name)
  stage          text not null,   -- extract|parse|map|convert|cluster|export
  state          text not null default 'open'
                 check (state in ('open','resolved','dismissed')),
  origin         text not null
                 check (origin in ('human_flag','machine_proposal','distance_gate')),
  payload        jsonb,           -- suggested-or-confirmed correction + machine context (candidates, reason)
  note           text,            -- optional free-text "what's wrong"
  origin_version text,            -- stage version that produced a machine proposal; null for human rows
  created_by     text,            -- auth.uid() (human) | job id | null
  reviewed_by    text,
  reviewed_at    timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- At most ONE active review per (entity, stage); resolved/dismissed rows
-- accumulate as history. A later re-flag opens a fresh row.
create unique index stage_reviews_one_open
  on stage_reviews (entity_kind, entity_id, stage) where state = 'open';

create index stage_reviews_queue_idx on stage_reviews (stage, state);

drop trigger if exists set_updated_at on stage_reviews;
create trigger set_updated_at
  before update on stage_reviews
  for each row execute function public.set_updated_at();

-- Audit trail, same as every other curated table.
create trigger audit_stage_reviews
  after insert or update or delete on stage_reviews
  for each row execute function audit.log_change();

-- Admin-only, like stage_runs: RLS on, authenticated-is_admin read. Writes go
-- through the security-definer RPCs below (which run as owner), so no direct
-- insert/update grant is needed.
alter table stage_reviews enable row level security;
grant select on stage_reviews to authenticated;
create policy stage_reviews_admin_read on stage_reviews
  for select to authenticated
  using (is_admin());

-- ---------------------------------------------------------------------------
-- 2. stage_runs -> append-versioned.
-- ---------------------------------------------------------------------------
-- History is kept instead of overwritten. Nothing references the old unique key
-- (the FKs on stage_runs are outgoing to jobs/job_batches), so the swap is safe.
alter table stage_runs
  drop constraint stage_runs_entity_type_entity_id_stage_key,
  add constraint stage_runs_entity_type_entity_id_stage_version_key
    unique (entity_type, entity_id, stage, version);

-- ---------------------------------------------------------------------------
-- 3. stage_live_version — per-stage live pointer.
-- ---------------------------------------------------------------------------
-- Which version is materialized into the live output tables. Defaults to the
-- latest run (Option-3 behavior unchanged); the deferred promote/rollback flips
-- it. The stage run path upserts this to its version on every run.
create table stage_live_version (
  stage   text primary key,
  version text not null
);

-- Read by the admin-only needs_review / outcome-count views (security-invoker),
-- so it needs the same authenticated-is_admin read surface as stage_runs.
alter table stage_live_version enable row level security;
grant select on stage_live_version to authenticated;
create policy stage_live_version_admin_read on stage_live_version
  for select to authenticated
  using (is_admin());

-- Backfill from the most recent run per stage so needs_review can filter to the
-- live version immediately (before any post-migration run repopulates it).
insert into stage_live_version (stage, version)
select distinct on (stage) stage, version
from stage_runs
order by stage, started_at desc
on conflict (stage) do nothing;

-- ---------------------------------------------------------------------------
-- 4. review_floors — per-stage confidence floor (distance-gate soft tier).
-- ---------------------------------------------------------------------------
-- floor_for(stage) returns this or 0.0 (flag nothing) when a stage has no row.
-- Seeded conservative (0.0 = off) until a follow-up sizes them from the real
-- best-candidate similarity distribution.
create table review_floors (
  stage text primary key,
  floor real not null default 0.0
);
insert into review_floors (stage, floor) values
  ('extract', 0.0), ('parse', 0.0), ('map', 0.0),
  ('convert', 0.0), ('cluster', 0.0), ('export', 0.0);

create or replace function floor_for(p_stage text) returns real
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((select floor from review_floors where stage = p_stage), 0.0);
$$;

-- ---------------------------------------------------------------------------
-- 5. apply_review — per-stage materialization of a resolved override.
-- ---------------------------------------------------------------------------
-- The SINGLE materialization authority. Branches on (stage, entity_kind) and
-- writes the resolved payload into that stage's live output table. Called from
-- resolve_review (web path) and the worker's Python re-apply loop, so a fix
-- lands identically whether just made or recomputed under.
create or replace function apply_review(p_id bigint) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  r stage_reviews;
begin
  select * into r from stage_reviews where id = p_id and state = 'resolved';
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
    -- parse re-parses (delete+reinsert) each rerun, so recipe_ingredient.id is
    -- not stable. Key by the stable (recipe_id, position): entity_id = "rid:pos".
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

-- ---------------------------------------------------------------------------
-- 6. flag_review — open a human flag (curator-only).
-- ---------------------------------------------------------------------------
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
  insert into stage_reviews (entity_kind, entity_id, stage, origin, note, created_by)
  values (p_entity_kind, p_entity_id, p_stage, 'human_flag', p_note, auth.uid()::text)
  on conflict (entity_kind, entity_id, stage) where state = 'open'
    do update set note = coalesce(excluded.note, stage_reviews.note),
                  updated_at = now()
  returning id into v_id;
  return v_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 7. resolve_review — set an override (or dismiss), then materialize.
-- ---------------------------------------------------------------------------
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
    update stage_reviews
       set state = 'dismissed', reviewed_by = auth.uid()::text, reviewed_at = now()
     where id = p_id;
    return;
  end if;
  update stage_reviews
     set state = 'resolved',
         payload = coalesce(p_payload, payload),
         reviewed_by = auth.uid()::text,
         reviewed_at = now()
   where id = p_id;
  perform apply_review(p_id);
end;
$$;

-- ---------------------------------------------------------------------------
-- 8. needs_review — the one derived curator queue (identical for every stage).
-- ---------------------------------------------------------------------------
-- No stored needs_review column/enum: open reviews UNION machine-couldn't-finish
-- (at the LIVE version) UNION auto-resolved-below-floor. Bump a floor or open a
-- review and the queue updates itself.
create or replace view needs_review
  with (security_invoker = true)
as
  select entity_kind, entity_id, stage, reason
  from (
    select entity_kind, entity_id, stage, origin as reason
      from stage_reviews
     where state = 'open'
    union all
    select sr.entity_type as entity_kind, sr.entity_id::text as entity_id, sr.stage,
           case when sr.confidence < floor_for(sr.stage) then 'low_confidence'
                else sr.outcome end as reason
      from stage_runs sr
      join stage_live_version lv on lv.stage = sr.stage and lv.version = sr.version
     where sr.outcome in ('abstain', 'proposes_new')
        or sr.confidence < floor_for(sr.stage)
  ) u;

grant select on needs_review to authenticated;

grant execute on function flag_review(text, text, text, text) to authenticated;
grant execute on function resolve_review(bigint, jsonb, boolean) to authenticated;

-- ---------------------------------------------------------------------------
-- 9. stage_run_outcome_counts -> count the LIVE version only.
-- ---------------------------------------------------------------------------
-- stage_runs is now append-versioned, so the original all-rows aggregate would
-- double-count an entity that has both an old and a current version. Filter to
-- the live version so the /ops dashboard reflects the current state, not history.
create or replace view stage_run_outcome_counts
  with (security_invoker = true)
as
select
  sr.stage,
  sr.outcome,
  count(*)::int                          as run_count,
  coalesce(sum(sr.cost_cents), 0)::numeric as cost_cents
from stage_runs sr
join stage_live_version lv on lv.stage = sr.stage and lv.version = sr.version
group by sr.stage, sr.outcome;
