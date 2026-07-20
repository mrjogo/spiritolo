-- Provisional taxonomy nodes (Phase 2).
--
-- `map-ingredient` now mints a node for any ingredient name it can't resolve to
-- an existing live node, instead of abstaining or proposing inline. A minted
-- node is `provisional` — it has no node_kind/parent yet and must NOT leak into
-- clustering, export, or the public taxonomy until the `combine-nodes` /
-- `connect-nodes` stages merge + place it and promote it to `live`.
--
-- The provisional/live distinction is a status flag on the canonical table (not
-- a staging table), so edges and resolutions reference a provisional node
-- natively and promotion is a cheap, auditable flag flip.

alter table public.taxonomy_nodes
  add column status text not null default 'live'
  check (status in ('live', 'provisional'));

-- Partial index: the hot lookups are "the provisional residue" (combine/connect
-- work queues) and the "any provisional?" downstream gate.
create index taxonomy_nodes_provisional_idx
  on public.taxonomy_nodes (status) where status = 'provisional';

-- Widen two CHECK domains for the mint path: map-ingredient writes a
-- `provisional` resolution and a `map-mint` provenance row (a deterministic
-- mint, not an LLM proposal, so it earns its own source label).
alter table public.ingredient_resolutions
  drop constraint ingredient_resolutions_method_check,
  add constraint ingredient_resolutions_method_check
    check (method in ('alias', 'lexical', 'llm', 'manual', 'abstain', 'provisional'));

alter table public.taxonomy_provenance
  drop constraint taxonomy_provenance_source_check,
  add constraint taxonomy_provenance_source_check
    check (source in ('seed', 'llm-mapper', 'manual', 'map-mint'));

-- Gate the public taxonomy view to live nodes only. (Otherwise unchanged — same
-- column list + lateral aggregates as the current definition.)
create or replace view public.taxonomy_public with (security_invoker = true) as
select
  n.id, n.slug, n.display_name, n.node_kind, n.default_role,
  n.is_cluster_node, n.is_defining_garnish,
  coalesce(p.parent_ids, '{}'::bigint[]) as parent_ids,
  coalesce(c.child_ids, '{}'::bigint[])  as child_ids,
  coalesce(a.aliases, '{}'::text[])      as aliases,
  coalesce(r.recipe_count, 0)            as recipe_count
from public.taxonomy_nodes n
  left join lateral (
    select array_agg(e.parent_id order by e.parent_id) as parent_ids
    from public.taxonomy_edges e where e.child_id = n.id
  ) p on true
  left join lateral (
    select array_agg(e.child_id order by e.child_id) as child_ids
    from public.taxonomy_edges e where e.parent_id = n.id
  ) c on true
  left join lateral (
    select array_agg(al.alias order by al.alias) as aliases
    from public.taxonomy_aliases al where al.node_id = n.id
  ) a on true
  left join lateral (
    select count(distinct ri.recipe_id)::int as recipe_count
    from public.ingredient_resolutions ir
    join public.recipe_ingredients ri on lower(btrim(ri.name)) = ir.normalized_name
    where ir.taxonomy_slug = n.slug
  ) r on true
where n.status = 'live';
