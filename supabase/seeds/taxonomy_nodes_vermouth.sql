-- Vermouth subtypes by sweetness/style.
-- EU regulation requires vermouth to contain wormwood, be ≥16% ABV,
-- and be wine-based. The major styles in cocktail recipes:
--   * sweet_vermouth (rosso, Italian style): garnet to dark caramel,
--     ~150 g/L sugar, herbaceous and slightly bitter. Manhattan,
--     Negroni, Americano, Boulevardier.
--   * dry_vermouth (French style): pale, <50 g/L sugar, herbaceous
--     and floral. Martini, Bamboo, Vesper, Adonis.
--   * blanc_vermouth (bianco / blanco): pale, semi-sweet, more floral
--     than rosso. Modern cocktails and white Negroni variants.
--
-- Style summaries verified via Difford's, Wikipedia, Saveur. Rosé
-- and amber styles are modern and less common in classic cocktail
-- recipes — skipped for tightness; D's mapper auto-creates expressions
-- when needed.
--
-- Note: a few prominent vermouth-adjacent products live elsewhere in
-- the seed:
--   * Cocchi Storico Vermouth di Torino is technically a sweet
--     vermouth but its brand `cocchi` was seeded in the fortified
--     wines PR; the storico expression can be auto-created by D when
--     recipes call it out.
--   * Punt e Mes is a sweet-vermouth + amaro hybrid, owned by Branca;
--     not seeded here — borderline brand-as-substance, deferred.
--   * Carpano Antica Formula is the iconic premium sweet vermouth,
--     also Branca-owned; auto-create on demand.

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('sweet_vermouth', 'Sweet Vermouth', true, 'modifier'),
  ('dry_vermouth',   'Dry Vermouth',   true, 'modifier'),
  ('blanc_vermouth', 'Blanc Vermouth', true, 'modifier');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('vermouth', 'sweet_vermouth'),
  ('vermouth', 'dry_vermouth'),
  ('vermouth', 'blanc_vermouth')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms covering Italian/French/style names.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('sweet vermouth',     'sweet_vermouth'),
  ('rosso vermouth',     'sweet_vermouth'),
  ('vermouth rosso',     'sweet_vermouth'),
  ('italian vermouth',   'sweet_vermouth'),
  ('red vermouth',       'sweet_vermouth'),
  ('dry vermouth',       'dry_vermouth'),
  ('french vermouth',    'dry_vermouth'),
  ('extra dry vermouth', 'dry_vermouth'),
  ('blanc vermouth',     'blanc_vermouth'),
  ('bianco vermouth',    'blanc_vermouth'),
  ('vermouth bianco',    'blanc_vermouth'),
  ('white vermouth',     'blanc_vermouth')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
