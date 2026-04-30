-- Tequila subtypes per the CRT (Consejo Regulador del Tequila) under
-- NOM-006-SCFI-2012. Five formal categories: blanco, joven (oro/gold,
-- a blend with reposado/añejo), reposado, añejo, extra añejo. Cluster
-- nodes seeded here are the four cocktail-relevant ones; joven/oro is
-- relatively rare in cocktail recipes and skipped for tightness.
--
-- Aging requirements per CRT:
--   * blanco: bottled within 60 days of distillation; most are
--     unaged but some are rested briefly in oak.
--   * reposado: ≥2 months in oak.
--   * añejo: ≥1 year in oak (≤600 L barrels).
--   * extra añejo: ≥3 years in oak (≤600 L barrels). Formalized in
--     2006.
--
-- Cristalino (charcoal-filtered añejo or extra añejo) is a market
-- style not formally recognized by the CRT — skipped here. If recipes
-- start calling it out as cluster identity, can be added.
--
-- Mezcal lives in `taxonomy_nodes_00_families.sql` as a top-level
-- cluster (no subtypes seeded).

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('blanco_tequila',      'Blanco Tequila',      true, 'base_spirit'),
  ('reposado_tequila',    'Reposado Tequila',    true, 'base_spirit'),
  ('anejo_tequila',       'Añejo Tequila',       true, 'base_spirit'),
  ('extra_anejo_tequila', 'Extra Añejo Tequila', true, 'base_spirit');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('tequila', 'blanco_tequila'),
  ('tequila', 'reposado_tequila'),
  ('tequila', 'anejo_tequila'),
  ('tequila', 'extra_anejo_tequila')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('blanco',              'blanco_tequila'),
  ('plata',               'blanco_tequila'),
  ('silver tequila',      'blanco_tequila'),
  ('plata tequila',       'blanco_tequila'),
  ('reposado',            'reposado_tequila'),
  ('anejo',               'anejo_tequila'),
  ('añejo',               'anejo_tequila'),
  ('extra anejo',         'extra_anejo_tequila'),
  ('extra añejo',         'extra_anejo_tequila'),
  ('extra-anejo',         'extra_anejo_tequila'),
  ('extra-añejo tequila', 'extra_anejo_tequila')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
