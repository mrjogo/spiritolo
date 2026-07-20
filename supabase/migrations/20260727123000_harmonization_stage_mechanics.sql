-- Harmonization stage mechanics (Phase 3.1) — shared plumbing for the two new
-- taxonomy stages `combine-nodes` and `connect-nodes`.
--
-- `map-ingredient` mints unresolved ingredient names as provisional
-- `taxonomy_nodes` (status='provisional', node_kind NULL, no parent edge). Two
-- new stages harmonize them: `combine-nodes` merges duplicates and
-- `connect-nodes` assigns node_kind + parent edges + is_cluster_node and
-- promotes the node to status='live'. This migration adds:
--
--   1. the `taxonomy_node` entity kind to the job_items entity_type CHECK,
--   2. `combine_merge()` — merge an absorbed node INTO a survivor,
--   3. `connect_place()` — place + promote a provisional node,
--   4. two new `apply_review()` dispatch branches so a resolved combine/connect
--      human review materializes through the same path as every other stage.
--
-- The two functions are the write actions both the stage_fns (auto-mode) and the
-- curator review path invoke. Existing migrations are immutable history; this is
-- a new forward migration.

-- ---------------------------------------------------------------------------
-- 1. Widen the job_items entity_type domain to include taxonomy nodes.
-- ---------------------------------------------------------------------------
-- combine-nodes / connect-nodes operate on taxonomy_node entities (map's entity
-- stays ingredient_name / recipe). The constraint kept its legacy stage_runs
-- name through the rename to job_items.
alter table public.job_items
  drop constraint stage_runs_entity_type_check,
  add constraint stage_runs_entity_type_check
    check (entity_type in ('page', 'recipe', 'taxonomy_node'));

-- ---------------------------------------------------------------------------
-- 2. combine_merge — merge the absorbed node INTO the survivor.
-- ---------------------------------------------------------------------------
-- Every reference to the absorbed node is repointed at the survivor, the
-- absorbed slug/display_name are kept as survivor aliases so future map lookups
-- land on the survivor, and the absorbed node is deleted. Edge/provenance/alias
-- rows FK-cascade on the node delete, but we repoint (and delete) explicitly so
-- the intent is legible and the survivor-equivalent edges exist first.
create or replace function public.combine_merge(
  p_survivor_id bigint,
  p_absorbed_id bigint
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_survivor_slug text;
  v_absorbed_slug text;
  v_absorbed_name text;
begin
  if p_survivor_id is null or p_absorbed_id is null then
    raise exception 'combine_merge: survivor and absorbed ids are both required';
  end if;
  if p_survivor_id = p_absorbed_id then
    raise exception 'combine_merge: cannot merge a node into itself (id %)', p_survivor_id;
  end if;

  select slug into v_survivor_slug from taxonomy_nodes where id = p_survivor_id;
  if v_survivor_slug is null then
    raise exception 'combine_merge: survivor node % not found', p_survivor_id;
  end if;
  select slug, display_name into v_absorbed_slug, v_absorbed_name
    from taxonomy_nodes where id = p_absorbed_id;
  if v_absorbed_slug is null then
    raise exception 'combine_merge: absorbed node % not found', p_absorbed_id;
  end if;

  -- Keep the absorbed node's slug + display name as survivor aliases so any name
  -- that previously mapped to the absorbed slug re-lands on the survivor.
  insert into taxonomy_aliases (alias, node_id)
  values (v_absorbed_slug, p_survivor_id)
  on conflict do nothing;
  insert into taxonomy_aliases (alias, node_id)
  values (v_absorbed_name, p_survivor_id)
  on conflict do nothing;

  -- Repoint the shared, name-keyed resolutions from the absorbed slug to the
  -- survivor slug.
  update ingredient_resolutions
     set taxonomy_slug = v_survivor_slug
   where taxonomy_slug = v_absorbed_slug;

  -- Repoint the parent side: edges where the absorbed node is the child become
  -- edges from the same parent to the survivor (skip a would-be self-loop).
  insert into taxonomy_edges (parent_id, child_id)
  select e.parent_id, p_survivor_id
    from taxonomy_edges e
   where e.child_id = p_absorbed_id
     and e.parent_id <> p_survivor_id
  on conflict do nothing;
  delete from taxonomy_edges where child_id = p_absorbed_id;

  -- Repoint the child side: edges where the absorbed node is the parent become
  -- edges from the survivor to the same child (skip a would-be self-loop).
  insert into taxonomy_edges (parent_id, child_id)
  select p_survivor_id, e.child_id
    from taxonomy_edges e
   where e.parent_id = p_absorbed_id
     and e.child_id <> p_survivor_id
  on conflict do nothing;
  delete from taxonomy_edges where parent_id = p_absorbed_id;

  -- Provenance is unique per node_id; the survivor keeps its own row. Drop the
  -- absorbed node's provenance before the node delete.
  delete from taxonomy_provenance where node_id = p_absorbed_id;

  delete from taxonomy_nodes where id = p_absorbed_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. connect_place — place + promote a provisional node.
-- ---------------------------------------------------------------------------
-- Attach the node under one or more existing parents, set its node_kind +
-- is_cluster_node, and flip status provisional -> live. When it becomes a
-- cluster node, enforce the antichain invariant (no is_cluster_node ancestor).
create or replace function public.connect_place(
  p_node_id         bigint,
  p_node_kind       text,
  p_parent_slugs    text[],
  p_is_cluster_node boolean
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_slug        text;
  v_parent_id   bigint;
  v_conflict_id bigint;
begin
  if p_node_id is null then
    raise exception 'connect_place: node id is required';
  end if;
  if not exists (select 1 from taxonomy_nodes where id = p_node_id) then
    raise exception 'connect_place: node % not found', p_node_id;
  end if;

  -- Resolve + attach each parent slug (skip a would-be self-loop).
  if p_parent_slugs is not null then
    foreach v_slug in array p_parent_slugs
    loop
      select id into v_parent_id from taxonomy_nodes where slug = v_slug;
      if v_parent_id is null then
        raise exception 'connect_place: parent slug % does not exist', v_slug;
      end if;
      if v_parent_id <> p_node_id then
        insert into taxonomy_edges (parent_id, child_id)
        values (v_parent_id, p_node_id)
        on conflict do nothing;
      end if;
    end loop;
  end if;

  -- Antichain invariant: a cluster node may not sit under another cluster node.
  -- Walk the edges upward from the node and reject any is_cluster_node ancestor.
  if p_is_cluster_node then
    with recursive ancestors(id) as (
      select e.parent_id from taxonomy_edges e where e.child_id = p_node_id
      union
      select e.parent_id from taxonomy_edges e join ancestors a on e.child_id = a.id
    )
    select an.id into v_conflict_id
      from ancestors an
      join taxonomy_nodes n on n.id = an.id
     where n.is_cluster_node
     limit 1;
    if v_conflict_id is not null then
      raise exception
        'connect_place: antichain violation — node % would be a cluster node under cluster ancestor %',
        p_node_id, v_conflict_id;
    end if;
  end if;

  update taxonomy_nodes
     set node_kind       = p_node_kind,
         is_cluster_node = p_is_cluster_node,
         status          = 'live',
         updated_at      = now()
   where id = p_node_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. apply_review — add the combine-nodes / connect-nodes dispatch branches.
-- ---------------------------------------------------------------------------
-- Copy of the current definition (from 20260727120000) with two branches added;
-- all existing branches are unchanged.
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

  elsif r.stage = 'combine-nodes' then
    perform combine_merge(
      (r.payload->>'survivor_id')::bigint,
      (r.payload->>'absorbed_id')::bigint
    );

  elsif r.stage = 'connect-nodes' then
    perform connect_place(
      r.entity_id::bigint,
      r.payload->>'node_kind',
      array(select jsonb_array_elements_text(r.payload->'parent_slugs')),
      coalesce((r.payload->>'is_cluster_node')::boolean, false)
    );
  end if;
end;
$$;
