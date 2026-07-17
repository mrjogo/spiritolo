-- Drop taxonomy_proposals — the last bespoke review mechanism, now folded into
-- stage_reviews (rows migrated by 20260724090000, writer switched in code).
--
-- Its only remaining readers are the two node-delete guards below, which count
-- proposals whose proposed_parent is the node being deleted. Repoint them at the
-- equivalent stage_reviews rows (open map machine_proposals of kind 'form'), then
-- drop the table — which also drops its RLS policies and audit trigger.

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
      select count(*)::int from public.stage_reviews
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
    from public.stage_reviews
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

drop table if exists taxonomy_proposals cascade;
