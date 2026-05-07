-- Taxonomy curation RPCs.
--
-- Five SECURITY DEFINER functions are the only write path for the curator
-- UI on taxonomy_nodes / taxonomy_edges / taxonomy_aliases. RLS on those
-- three tables stays deny-all (enabled, no policies); the functions
-- bypass RLS by virtue of running as the function owner.
--
-- All five guard on public.is_admin(). The read-only blocker counter
-- (get_taxonomy_node_blockers) is separated from the destructive
-- delete_taxonomy_node so the UI can preflight without invoking the
-- delete path.

------------------------------------------------------------------------
-- get_taxonomy_node_blockers(id) — read-only preflight for delete UI
------------------------------------------------------------------------
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
      select count(*)::int from public.recipe_ingredients where taxonomy_node_id = p_id
    ),
    'taxonomy_proposals', (
      select count(*)::int from public.taxonomy_proposals where proposed_parent_id = p_id
    )
  );
end;
$$;

grant execute on function public.get_taxonomy_node_blockers(bigint) to authenticated;

------------------------------------------------------------------------
-- create_taxonomy_node(...) — atomic node + edge + aliases insert
------------------------------------------------------------------------
create or replace function public.create_taxonomy_node(
  p_parent_id           bigint,
  p_slug                text,
  p_display_name        text,
  p_node_kind           text default null,
  p_default_role        text default null,
  p_is_cluster_node     boolean default false,
  p_is_defining_garnish boolean default false,
  p_aliases             text[] default '{}'::text[]
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_new_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if p_parent_id is not null
     and not exists (select 1 from public.taxonomy_nodes where id = p_parent_id) then
    raise exception 'parent_id % not found', p_parent_id using errcode = '23503';
  end if;

  insert into public.taxonomy_nodes (
    slug, display_name, node_kind, default_role,
    is_cluster_node, is_defining_garnish
  )
  values (
    p_slug, p_display_name, p_node_kind, p_default_role,
    p_is_cluster_node, p_is_defining_garnish
  )
  returning id into v_new_id;

  if p_parent_id is not null then
    insert into public.taxonomy_edges (parent_id, child_id)
    values (p_parent_id, v_new_id);
  end if;

  insert into public.taxonomy_aliases (alias, node_id)
  select a, v_new_id
  from unnest(p_aliases) as a
  where a is not null and trim(a) <> '';

  return v_new_id;
end;
$$;

grant execute on function public.create_taxonomy_node(
  bigint, text, text, text, text, boolean, boolean, text[]
) to authenticated;

------------------------------------------------------------------------
-- update_taxonomy_node(id, patch jsonb) — partial update
------------------------------------------------------------------------
-- Patch keys recognized: slug, display_name, node_kind, default_role,
-- is_cluster_node, is_defining_garnish, aliases. Missing keys leave
-- the column alone. Explicit JSON null in node_kind / default_role
-- sets the column to NULL (those columns are nullable). Aliases is
-- replace-all when present.
create or replace function public.update_taxonomy_node(
  p_id    bigint,
  p_patch jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  update public.taxonomy_nodes
  set
    slug         = case when p_patch ? 'slug' then p_patch->>'slug' else slug end,
    display_name = case when p_patch ? 'display_name' then p_patch->>'display_name' else display_name end,
    node_kind    = case when p_patch ? 'node_kind' then nullif(p_patch->>'node_kind', '') else node_kind end,
    default_role = case when p_patch ? 'default_role' then nullif(p_patch->>'default_role', '') else default_role end,
    is_cluster_node = case
      when p_patch ? 'is_cluster_node' then (p_patch->>'is_cluster_node')::boolean
      else is_cluster_node
    end,
    is_defining_garnish = case
      when p_patch ? 'is_defining_garnish' then (p_patch->>'is_defining_garnish')::boolean
      else is_defining_garnish
    end
  where id = p_id;

  if p_patch ? 'aliases' then
    delete from public.taxonomy_aliases where node_id = p_id;
    insert into public.taxonomy_aliases (alias, node_id)
    select a, p_id
    from jsonb_array_elements_text(p_patch->'aliases') as t(a)
    where a is not null and trim(a) <> '';
  end if;
end;
$$;

grant execute on function public.update_taxonomy_node(bigint, jsonb) to authenticated;

------------------------------------------------------------------------
-- set_node_parents(id, parent_ids[]) — replace edge set, reject cycles
------------------------------------------------------------------------
create or replace function public.set_node_parents(
  p_id         bigint,
  p_parent_ids bigint[]
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  if p_id = any(coalesce(p_parent_ids, '{}'::bigint[])) then
    raise exception 'cycle: a node cannot be its own parent' using errcode = '23514';
  end if;

  -- Reject if any proposed parent is a (transitive) descendant of p_id.
  if exists (
    with recursive descendants as (
      select child_id from public.taxonomy_edges where parent_id = p_id
      union
      select e.child_id
      from public.taxonomy_edges e
      join descendants d on e.parent_id = d.child_id
    )
    select 1 from descendants
    where child_id = any(coalesce(p_parent_ids, '{}'::bigint[]))
  ) then
    raise exception 'cycle: at least one proposed parent is a descendant of node %', p_id
      using errcode = '23514';
  end if;

  delete from public.taxonomy_edges where child_id = p_id;
  insert into public.taxonomy_edges (parent_id, child_id)
  select p, p_id
  from unnest(coalesce(p_parent_ids, '{}'::bigint[])) as p
  where p is not null;
end;
$$;

grant execute on function public.set_node_parents(bigint, bigint[]) to authenticated;

------------------------------------------------------------------------
-- delete_taxonomy_node(id) — refuse if children / refs exist
------------------------------------------------------------------------
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
    from public.recipe_ingredients where taxonomy_node_id = p_id;
  select count(*) into v_proposals
    from public.taxonomy_proposals where proposed_parent_id = p_id;

  if v_children > 0 or v_recipes > 0 or v_proposals > 0 then
    raise exception
      'blocked: % children, % recipe references, % proposal references',
      v_children, v_recipes, v_proposals
      using errcode = '23503',
            detail = jsonb_build_object(
              'children', v_children,
              'recipe_ingredients', v_recipes,
              'taxonomy_proposals', v_proposals
            )::text;
  end if;

  delete from public.taxonomy_nodes where id = p_id;
end;
$$;

grant execute on function public.delete_taxonomy_node(bigint) to authenticated;
