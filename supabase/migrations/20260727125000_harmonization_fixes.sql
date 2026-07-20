-- Harmonization mechanics — self-review fixes.
--
-- Three correctness fixes to the combine/connect plumbing added in
-- 20260727123000, from a code review of this branch:
--   1. combine_merge: repoint the absorbed node's OWN aliases to the survivor
--      before deleting it (previously they FK-cascade-deleted, losing curated
--      alias spellings on a broad live->live merge).
--   2. connect_place: the antichain guard walked ancestors only; also reject an
--      is_cluster_node DESCENDANT (promoting a node to a cluster node above an
--      existing cluster node also violates "no is_cluster_node ancestor").
--   3. apply_review combine-nodes branch: take the absorbed node id from the
--      review's own entity_id (like the connect-nodes branch uses it for the
--      node id) rather than trusting a redundant payload field — a curator can't
--      merge the wrong node by mistyping absorbed_id.

-- ---------------------------------------------------------------------------
-- 1. combine_merge — also repoint the absorbed node's aliases to the survivor.
-- ---------------------------------------------------------------------------
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

  -- Move the absorbed node's own aliases to the survivor (so a broad live->live
  -- merge doesn't lose curated spellings), then add the absorbed slug + display
  -- name as survivor aliases so any name that mapped to the absorbed re-lands on
  -- the survivor.
  update taxonomy_aliases a
     set node_id = p_survivor_id
   where a.node_id = p_absorbed_id
     and not exists (
       select 1 from taxonomy_aliases s
        where s.node_id = p_survivor_id and s.alias = a.alias
     );
  delete from taxonomy_aliases where node_id = p_absorbed_id;
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

  -- Repoint the parent side (absorbed as child) then the child side (absorbed as
  -- parent), skipping would-be self-loops; delete the absorbed node's edges.
  insert into taxonomy_edges (parent_id, child_id)
  select e.parent_id, p_survivor_id
    from taxonomy_edges e
   where e.child_id = p_absorbed_id
     and e.parent_id <> p_survivor_id
  on conflict do nothing;
  delete from taxonomy_edges where child_id = p_absorbed_id;

  insert into taxonomy_edges (parent_id, child_id)
  select p_survivor_id, e.child_id
    from taxonomy_edges e
   where e.parent_id = p_absorbed_id
     and e.child_id <> p_survivor_id
  on conflict do nothing;
  delete from taxonomy_edges where parent_id = p_absorbed_id;

  delete from taxonomy_provenance where node_id = p_absorbed_id;
  delete from taxonomy_nodes where id = p_absorbed_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 2. connect_place — antichain guard walks ancestors AND descendants.
-- ---------------------------------------------------------------------------
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

  -- Antichain invariant: an is_cluster_node node may have neither an
  -- is_cluster_node ancestor NOR an is_cluster_node descendant. Two separate
  -- upward/downward walks (the parent edges just added are already in place).
  if p_is_cluster_node then
    with recursive ancestors(id) as (
      select e.parent_id from taxonomy_edges e where e.child_id = p_node_id
      union
      select e.parent_id from taxonomy_edges e join ancestors a on e.child_id = a.id
    )
    select an.id into v_conflict_id
      from ancestors an join taxonomy_nodes n on n.id = an.id
     where n.is_cluster_node
     limit 1;

    if v_conflict_id is null then
      with recursive descendants(id) as (
        select e.child_id from taxonomy_edges e where e.parent_id = p_node_id
        union
        select e.child_id from taxonomy_edges e join descendants d on e.parent_id = d.id
      )
      select de.id into v_conflict_id
        from descendants de join taxonomy_nodes n on n.id = de.id
       where n.is_cluster_node
       limit 1;
    end if;

    if v_conflict_id is not null then
      raise exception
        'connect_place: antichain violation — node % would be a cluster node with cluster relative %',
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
-- 3. apply_review — combine-nodes branch takes absorbed_id from entity_id.
-- ---------------------------------------------------------------------------
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
    -- absorbed = the node under review (entity_id); only survivor_id comes from
    -- the curator's payload, so a mistyped/omitted id can't merge the wrong node.
    perform combine_merge(
      (r.payload->>'survivor_id')::bigint,
      r.entity_id::bigint
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
