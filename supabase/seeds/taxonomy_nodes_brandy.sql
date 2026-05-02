-- Brandy subtypes by regional designation. Each is a protected origin
-- with distinct production rules and cocktail vocabulary:
--   * cognac: AOC-protected, from the Cognac region of southwestern
--     France; double-distilled in pot stills; aged ≥2 years in oak;
--     VS / VSOP / XO age categories on top. Sidecar, Vieux Carré,
--     Brandy Crusta.
--   * armagnac: AOC-protected, Gascony region of France; column-
--     distilled (single distillation traditionally); aged ≥2 years.
--     Less common in cocktails than cognac but appears in modern
--     riffs and stirred drinks.
--   * calvados: AOC-protected, Normandy region; distilled from cider
--     (apples and sometimes pears). Apple Brandy, Jack Rose (with
--     applejack as American substitute), Vieux Carré variant.
--   * pisco: protected designation in both Peru and Chile (separate
--     denominaciones de origen); grape-based brandy, traditionally
--     unaged. Pisco Sour, Pisco Punch.
--
-- Skipped: Brandy de Jerez (Spanish, less common in classic cocktails),
-- American brandy (generic, less called-out), grappa (pomace brandy,
-- typically used in digestifs not cocktails), eau-de-vie (fruit
-- brandies, too varied for a single cluster). D's mapper auto-creates
-- expressions when needed.

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('cognac',   'Cognac',   true, 'base_spirit'),
  ('armagnac', 'Armagnac', true, 'base_spirit'),
  ('calvados', 'Calvados', true, 'base_spirit'),
  ('pisco',    'Pisco',    true, 'base_spirit');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('brandy', 'cognac'),
  ('brandy', 'armagnac'),
  ('brandy', 'calvados'),
  ('brandy', 'pisco')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms. 'apple brandy' is intentionally
-- not aliased to calvados — American applejack and French calvados are
-- functionally similar but distinct products, and recipes that say
-- "apple brandy" without specifying which surface as underspecified.
-- 'peruvian pisco' / 'chilean pisco' route to the same cluster despite
-- the two countries' separate DO regimes — cocktail recipes don't
-- typically distinguish, and brand call (BarSol vs Capel etc.)
-- survives at variant level.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('peruvian pisco', 'pisco'),
  ('chilean pisco',  'pisco')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
