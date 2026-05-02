-- Public read surface for the taxonomy DAG. One row per node with edges
-- and aliases pre-aggregated and a direct (non-rollup) recipe count.
-- Mirrors the recipes_public pattern: security_invoker = true plus
-- public-read policies and column-level grants on each underlying table.
-- recipe_ingredients exposes only (recipe_id, taxonomy_node_id) so the
-- view can compute counts without leaking parser internals to anon.

create view taxonomy_public
  with (security_invoker = true)
as
select
  n.id,
  n.slug,
  n.display_name,
  n.role,
  n.role_default,
  n.is_cluster_node,
  n.is_defining_garnish,
  coalesce(p.parent_ids, '{}'::bigint[]) as parent_ids,
  coalesce(c.child_ids,  '{}'::bigint[]) as child_ids,
  coalesce(a.aliases,    '{}'::text[])   as aliases,
  coalesce(r.recipe_count, 0)            as recipe_count
from taxonomy_nodes n
left join lateral (
  select array_agg(parent_id order by parent_id) as parent_ids
  from taxonomy_edges where child_id = n.id
) p on true
left join lateral (
  select array_agg(child_id order by child_id) as child_ids
  from taxonomy_edges where parent_id = n.id
) c on true
left join lateral (
  select array_agg(alias order by alias) as aliases
  from taxonomy_aliases where node_id = n.id
) a on true
left join lateral (
  select count(distinct recipe_id)::int as recipe_count
  from recipe_ingredients
  where taxonomy_node_id = n.id
) r on true;

grant select on taxonomy_public to anon, authenticated;

-- taxonomy_nodes: full column-level grant + public-read policy.
grant select (
  id, slug, display_name, role, role_default,
  is_cluster_node, is_defining_garnish, created_at
) on taxonomy_nodes to anon, authenticated;

create policy taxonomy_nodes_public_read on taxonomy_nodes
  for select to anon, authenticated using (true);

-- taxonomy_edges: full column-level grant + public-read policy.
grant select (parent_id, child_id) on taxonomy_edges to anon, authenticated;

create policy taxonomy_edges_public_read on taxonomy_edges
  for select to anon, authenticated using (true);

-- taxonomy_aliases: full column-level grant + public-read policy.
grant select (alias, node_id) on taxonomy_aliases to anon, authenticated;

create policy taxonomy_aliases_public_read on taxonomy_aliases
  for select to anon, authenticated using (true);

-- recipe_ingredients: tightly scoped grant — only the two columns the
-- view needs to compute recipe_count. Parser internals stay private.
grant select (recipe_id, taxonomy_node_id)
  on recipe_ingredients to anon, authenticated;

create policy recipe_ingredients_taxonomy_count_read on recipe_ingredients
  for select to anon, authenticated using (true);
