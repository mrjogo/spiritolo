-- After 20260502120000 renamed taxonomy_nodes.role -> node_kind and
-- role_default -> default_role, the dependent taxonomy_public view's
-- output columns landed in an inconsistent state on some local DBs:
-- the view's stored definition tracks the rename, but the OUTPUT
-- column names the view exposes to clients did not, so SELECTs that
-- name `node_kind` or `default_role` against the view fail with
-- "column taxonomy_public.node_kind does not exist".
--
-- Forward-only fix: drop and recreate the view so its output columns
-- are unambiguously named `node_kind` and `default_role`. Mirrors
-- 20260501120000's body except that the projection now references
-- the post-rename table column names directly.

drop view if exists taxonomy_public;

create view taxonomy_public
  with (security_invoker = true)
as
select
  n.id,
  n.slug,
  n.display_name,
  n.node_kind,
  n.default_role,
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
