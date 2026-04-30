-- Top-level spirit families and base liqueurs.
insert into taxonomy_nodes (slug, display_name) values
  ('whiskey',  'Whiskey'),
  ('gin',      'Gin'),
  ('vodka',    'Vodka'),
  ('rum',      'Rum'),
  ('tequila',  'Tequila'),
  ('mezcal',   'Mezcal'),
  ('brandy',   'Brandy'),
  ('vermouth', 'Vermouth'),
  ('amaro',    'Amaro'),
  ('bitters',  'Bitters');

-- Whiskey subtypes.
insert into taxonomy_nodes (slug, display_name) values
  ('bourbon',         'Bourbon'),
  ('rye_whiskey',     'Rye Whiskey'),
  ('scotch_whisky',   'Scotch Whisky'),
  ('irish_whiskey',   'Irish Whiskey'),
  ('japanese_whisky', 'Japanese Whisky');

-- Rum / Tequila / Vermouth / Brandy subtypes.
insert into taxonomy_nodes (slug, display_name) values
  ('white_rum',        'White Rum'),
  ('dark_rum',         'Dark Rum'),
  ('aged_rum',         'Aged Rum'),
  ('blanco_tequila',   'Blanco Tequila'),
  ('reposado_tequila', 'Reposado Tequila'),
  ('anejo_tequila',    'Añejo Tequila'),
  ('sweet_vermouth',   'Sweet Vermouth'),
  ('dry_vermouth',     'Dry Vermouth'),
  ('blanc_vermouth',   'Blanc Vermouth'),
  ('cognac',           'Cognac'),
  ('armagnac',         'Armagnac'),
  ('calvados',         'Calvados');

-- Produce.
insert into taxonomy_nodes (slug, display_name) values
  ('citrus',     'Citrus'),
  ('lemon',      'Lemon'),
  ('lime',       'Lime'),
  ('orange',     'Orange'),
  ('grapefruit', 'Grapefruit');

-- Edges: parent_slug -> child_slug.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('whiskey',  'bourbon'),
  ('whiskey',  'rye_whiskey'),
  ('whiskey',  'scotch_whisky'),
  ('whiskey',  'irish_whiskey'),
  ('whiskey',  'japanese_whisky'),
  ('rum',      'white_rum'),
  ('rum',      'dark_rum'),
  ('rum',      'aged_rum'),
  ('tequila',  'blanco_tequila'),
  ('tequila',  'reposado_tequila'),
  ('tequila',  'anejo_tequila'),
  ('vermouth', 'sweet_vermouth'),
  ('vermouth', 'dry_vermouth'),
  ('vermouth', 'blanc_vermouth'),
  ('brandy',   'cognac'),
  ('brandy',   'armagnac'),
  ('brandy',   'calvados'),
  ('citrus',   'lemon'),
  ('citrus',   'lime'),
  ('citrus',   'orange'),
  ('citrus',   'grapefruit')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: free-text strings recipes use, mapped to canonical nodes.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('whisky',           'whiskey'),
  ('rye',              'rye_whiskey'),
  ('rye whiskey',      'rye_whiskey'),
  ('scotch',           'scotch_whisky'),
  ('single malt',      'scotch_whisky'),
  ('bourbon whiskey',  'bourbon'),
  ('blanco',           'blanco_tequila'),
  ('reposado',         'reposado_tequila'),
  ('anejo',            'anejo_tequila'),
  ('añejo',            'anejo_tequila'),
  ('sweet vermouth',   'sweet_vermouth'),
  ('rosso vermouth',   'sweet_vermouth'),
  ('italian vermouth', 'sweet_vermouth'),
  ('dry vermouth',     'dry_vermouth'),
  ('french vermouth',  'dry_vermouth')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;

-- Bitters.
-- Antichain (is_cluster_node = true) sits at the type level uniformly across
-- the bitters family: angostura_style_aromatic_bitters, orange_bitters,
-- chocolate_bitters, creole_bitters. Brands sit under `bitters`; named
-- products are role='expression' nodes with two parents — their brand and
-- their type — so the cluster-key rollup deterministically lands at the
-- type cluster_node. Brand call (e.g. Angostura vs Bittercube Aromatic)
-- survives at the variant level via the expression's taxonomy_node_id.
update taxonomy_nodes set role_default = 'bitters' where slug = 'bitters';

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('angostura_style_aromatic_bitters', 'Angostura-Style Aromatic Bitters', true, 'bitters'),
  ('orange_bitters',                   'Orange Bitters',                   true, 'bitters'),
  ('chocolate_bitters',                'Chocolate Bitters',                true, 'bitters'),
  ('creole_bitters',                   'Creole Bitters',                   true, 'bitters');

-- Brand nodes. `regans` is single-product (orange bitters only) so it sits
-- under orange_bitters directly. The multi-product brands sit under `bitters`
-- and each of their expressions gets dual parentage [brand, type].
insert into taxonomy_nodes (slug, display_name, role) values
  ('angostura',        'Angostura',         'brand'),
  ('peychauds',        'Peychaud''s',       'brand'),
  ('regans',           'Regan''s',          'brand'),
  ('fee_brothers',     'Fee Brothers',      'brand'),
  ('bittermens',       'Bittermens',        'brand'),
  ('the_bitter_truth', 'The Bitter Truth',  'brand');

-- Expression nodes. None are cluster nodes; each rolls up to its type cluster.
-- Slugs use the manufacturer's full product name in snake_case so future siblings
-- have room (Angostura Orange Bitters lives next to Angostura Aromatic Bitters).
insert into taxonomy_nodes (slug, display_name, role, role_default) values
  ('angostura_aromatic_bitters',              'Angostura Aromatic Bitters',              'expression', 'bitters'),
  ('angostura_orange_bitters',                'Angostura Orange Bitters',                'expression', 'bitters'),
  ('peychauds_bitters',                       'Peychaud''s Bitters',                     'expression', 'bitters'),
  ('regans_orange_bitters',                   'Regan''s Orange Bitters No. 6',           'expression', 'bitters'),
  ('fee_brothers_west_indian_orange_bitters', 'Fee Brothers West Indian Orange Bitters', 'expression', 'bitters'),
  ('bittermens_xocolatl_mole_bitters',        'Bittermens Xocolatl Mole Bitters',        'expression', 'bitters'),
  ('the_bitter_truth_creole_bitters',         'The Bitter Truth Creole Bitters',         'expression', 'bitters');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  -- type cluster nodes under `bitters`
  ('bitters',                        'angostura_style_aromatic_bitters'),
  ('bitters',                        'orange_bitters'),
  ('bitters',                        'chocolate_bitters'),
  ('bitters',                        'creole_bitters'),
  -- brands. Single-product brand sits under its one type; multi-product brands
  -- and the historically-iconic single-product brands (angostura, peychauds)
  -- sit directly under `bitters` so the brand node itself is style-agnostic.
  ('bitters',                        'angostura'),
  ('bitters',                        'peychauds'),
  ('orange_bitters',                 'regans'),
  ('bitters',                        'fee_brothers'),
  ('bitters',                        'bittermens'),
  ('bitters',                        'the_bitter_truth'),
  -- expressions: dual-parent [brand, type] so rollup lands at the type cluster.
  ('angostura',                       'angostura_aromatic_bitters'),
  ('angostura_style_aromatic_bitters','angostura_aromatic_bitters'),
  ('angostura',                       'angostura_orange_bitters'),
  ('orange_bitters',                  'angostura_orange_bitters'),
  ('peychauds',                       'peychauds_bitters'),
  ('creole_bitters',                  'peychauds_bitters'),
  -- regans is parented under its only type already, so its expression only
  -- needs the brand parent (rollup walks brand → orange_bitters cluster).
  ('regans',                          'regans_orange_bitters'),
  ('fee_brothers',                    'fee_brothers_west_indian_orange_bitters'),
  ('orange_bitters',                  'fee_brothers_west_indian_orange_bitters'),
  ('bittermens',                      'bittermens_xocolatl_mole_bitters'),
  ('chocolate_bitters',               'bittermens_xocolatl_mole_bitters'),
  ('the_bitter_truth',                'the_bitter_truth_creole_bitters'),
  ('creole_bitters',                  'the_bitter_truth_creole_bitters')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: variants of canonical names. Product names are NEVER aliases —
-- they are the expression nodes above. The 'aromatic bitters' generic and
-- 'angostura' shorthand alias to the angostura_aromatic_bitters expression
-- because cocktail vocabulary equates them with that canonical product;
-- the variant_key still preserves the specific brand call.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('aromatic bitters',           'angostura_aromatic_bitters'),
  ('angostura',                  'angostura_aromatic_bitters'),
  ('angostura bitters',          'angostura_aromatic_bitters'),
  ('angostura aromatic bitters', 'angostura_aromatic_bitters'),
  ('angostura orange',           'angostura_orange_bitters'),
  ('angostura orange bitters',   'angostura_orange_bitters'),
  ('peychauds',                  'peychauds_bitters'),
  ('peychaud''s',                'peychauds_bitters'),
  ('peychaud''s bitters',        'peychauds_bitters'),
  ('creole bitters',             'creole_bitters'),
  -- Variants of expression display names.
  ('regans orange bitters',                    'regans_orange_bitters'),
  ('regan''s orange bitters',                  'regans_orange_bitters'),
  ('regans orange bitters no 6',               'regans_orange_bitters'),
  ('regan''s orange bitters no. 6',            'regans_orange_bitters'),
  ('fee brothers orange bitters',              'fee_brothers_west_indian_orange_bitters'),
  ('fee brothers west indian orange bitters',  'fee_brothers_west_indian_orange_bitters'),
  ('bittermens mole bitters',                  'bittermens_xocolatl_mole_bitters'),
  ('bittermens xocolatl mole bitters',         'bittermens_xocolatl_mole_bitters'),
  ('xocolatl mole bitters',                    'bittermens_xocolatl_mole_bitters'),
  ('the bitter truth creole bitters',          'the_bitter_truth_creole_bitters'),
  ('bitter truth creole bitters',              'the_bitter_truth_creole_bitters')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
