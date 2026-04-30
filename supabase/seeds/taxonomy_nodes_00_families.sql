-- Top-level family parents (loads first per the `00_` numeric prefix).
-- All other family files reference these parents in their edges, so this
-- file must load before them.
--
-- Most families are non-cluster navigation parents — recipes specifying
-- the bare family name (`whiskey`, `rum`, `tequila`, `brandy`, `gin`,
-- `vermouth`, `amaro`, `bitters`) surface as underspecified and the
-- audit pass flags them. The subtypes live in per-family files
-- (taxonomy_nodes_whiskey.sql, etc.).
--
-- vodka and mezcal are top-level cluster nodes themselves — neither has
-- cocktail-relevant subtypes that meaningfully change drink identity.
-- Per the dedup spec antichain definition. If finer-grained subtypes
-- are seeded later (mezcal espadín vs tobalá; vodka categories) the
-- cluster annotation moves to the children.
--
-- role_default values follow the dedup spec's role allowlist:
-- base_spirit / modifier / citrus / sweetener / bitters / dilution /
-- ice / garnish / wash / other. Vermouth defaults to 'modifier' (the
-- contextual rule promotes to 'base_spirit' in Reverse Manhattan /
-- Bamboo / Adonis when amount ≥ 1.5 oz).

insert into taxonomy_nodes (slug, display_name, role_default) values
  ('whiskey',  'Whiskey',  'base_spirit'),
  ('gin',      'Gin',      'base_spirit'),
  ('rum',      'Rum',      'base_spirit'),
  ('tequila',  'Tequila',  'base_spirit'),
  ('brandy',   'Brandy',   'base_spirit'),
  ('vermouth', 'Vermouth', 'modifier'),
  ('amaro',    'Amaro',    'modifier'),
  ('bitters',  'Bitters',  'bitters');

-- Top-level cluster nodes (no subtypes seeded — cluster identity is the
-- family itself; brands and finer-grained details survive at variant level).
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('vodka',  'Vodka',  true, 'base_spirit'),
  ('mezcal', 'Mezcal', true, 'base_spirit');

-- Aliases: spelling variants and cocktail-vocabulary shortcuts. Bare
-- family-name aliases (e.g. 'rum' → rum) are NOT seeded — those should
-- surface as underspecified.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('whisky', 'whiskey')  -- non-American spelling; ambiguous in cocktail vocab (could mean Scotch/Japanese/Canadian) so routes to family parent and surfaces as underspecified
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
