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

-- E [Phase 10]: starter antichain markers + role_defaults on existing nodes.
-- The full curator-track expansion (gin sub-styles, individual amari,
-- individual bitters, key liqueurs, fortified wines, broader categories)
-- runs as parallel reviewer-gated PRs. This is the minimum needed for
-- the dev DB to exercise the dedup pipeline.

-- Mark whiskey subtypes as antichain.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('bourbon', 'rye_whiskey', 'scotch_whisky', 'irish_whiskey',
                'japanese_whisky');

-- Vermouth subtypes (already in seed; add antichain + role_default).
update taxonomy_nodes set is_cluster_node = true, role_default = 'modifier'
 where slug in ('sweet_vermouth', 'dry_vermouth', 'blanc_vermouth');

-- Rum + tequila subtypes.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('white_rum', 'dark_rum', 'aged_rum',
                'blanco_tequila', 'reposado_tequila', 'anejo_tequila',
                'mezcal');

-- Brandy subtypes.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('cognac', 'armagnac', 'calvados');

-- Citrus produce (existing).
update taxonomy_nodes set role_default = 'citrus'
 where slug in ('lemon', 'lime', 'orange', 'grapefruit');

-- Add a starter set of nodes that don't exist in the current seed but
-- are essential for the dedup pipeline to do useful work.
insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  -- Gin sub-styles (definitional)
  ('london_dry_gin',      'London Dry Gin',      null, true, 'base_spirit'),
  ('old_tom_gin',         'Old Tom Gin',         null, true, 'base_spirit'),
  ('plymouth_gin',        'Plymouth Gin',        null, true, 'base_spirit'),
  -- Bitters (definitional, not brand-modeled)
  ('angostura_bitters',   'Angostura Bitters',   null, true, 'bitters'),
  ('peychauds_bitters',   'Peychauds Bitters',   null, true, 'bitters'),
  ('orange_bitters',      'Orange Bitters',      null, true, 'bitters'),
  -- Amari (definitional)
  ('campari',             'Campari',             null, true, 'modifier'),
  ('aperol',              'Aperol',              null, true, 'modifier'),
  -- Sweeteners
  ('simple_syrup',        'Simple Syrup',        null, true, 'sweetener'),
  ('demerara_syrup',      'Demerara Syrup',      null, true, 'sweetener'),
  ('honey_syrup',         'Honey Syrup',         null, true, 'sweetener'),
  -- Citrus juices (form nodes; D's mapper may auto-create these too)
  ('lemon_juice',         'Lemon Juice',         null, true, 'citrus'),
  ('lime_juice',          'Lime Juice',          null, true, 'citrus'),
  ('orange_juice',        'Orange Juice',        null, true, 'citrus'),
  ('grapefruit_juice',    'Grapefruit Juice',    null, true, 'citrus'),
  -- Dilution + ice
  ('soda_water',          'Soda Water',          null, true, 'dilution'),
  ('tonic_water',         'Tonic Water',         null, true, 'dilution'),
  ('ice',                 'Ice',                 null, true, 'ice'),
  -- Defining garnishes
  ('cocktail_onion',      'Cocktail Onion',      null, true, 'garnish'),
  ('salt_rim',            'Salt Rim',            null, true, 'garnish')
on conflict (slug) do nothing;

-- Mark defining-garnish flags.
update taxonomy_nodes set is_defining_garnish = true
 where slug in ('cocktail_onion', 'salt_rim');

-- Edges for new sub-style nodes.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('gin', 'london_dry_gin'),
  ('gin', 'old_tom_gin'),
  ('gin', 'plymouth_gin'),
  ('bitters', 'angostura_bitters'),
  ('bitters', 'peychauds_bitters'),
  ('bitters', 'orange_bitters'),
  ('amaro', 'campari'),
  ('amaro', 'aperol'),
  ('lemon', 'lemon_juice'),
  ('lime',  'lime_juice'),
  ('orange', 'orange_juice'),
  ('grapefruit', 'grapefruit_juice')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug
on conflict do nothing;

-- Aliases for the new substance nodes.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('london dry',         'london_dry_gin'),
  ('old tom',            'old_tom_gin'),
  ('angostura',          'angostura_bitters'),
  ('peychauds',          'peychauds_bitters'),
  ('peychaud''s',        'peychauds_bitters'),
  ('orange bitter',      'orange_bitters'),
  ('lemon juice',        'lemon_juice'),
  ('lime juice',         'lime_juice'),
  ('fresh lemon juice',  'lemon_juice'),
  ('fresh lime juice',   'lime_juice'),
  ('simple',             'simple_syrup'),
  ('demerara',           'demerara_syrup'),
  ('honey',              'honey_syrup'),
  ('soda',               'soda_water'),
  ('club soda',          'soda_water'),
  ('tonic',              'tonic_water')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug
on conflict do nothing;

-- Cocktail aliases — starter seed for E's name normalizer.
insert into cocktail_aliases (alias, canonical_name, source) values
  ('negroni',          'negroni',         'seed'),
  ('old fashioned',    'old fashioned',   'seed'),
  ('manhattan',        'manhattan',       'seed'),
  ('martini',          'martini',         'seed'),
  ('daiquiri',         'daiquiri',        'seed'),
  ('daquiri',          'daiquiri',        'seed'),
  ('margarita',        'margarita',       'seed'),
  ('whiskey sour',     'whiskey sour',    'seed'),
  ('whisky sour',      'whiskey sour',    'seed'),
  ('tom collins',      'tom collins',     'seed'),
  ('gimlet',           'gimlet',          'seed'),
  ('aviation',         'aviation',        'seed'),
  ('last word',        'last word',       'seed'),
  ('sazerac',          'sazerac',         'seed'),
  ('sidecar',          'sidecar',         'seed'),
  ('vesper',           'vesper',          'seed'),
  ('boulevardier',     'boulevardier',    'seed'),
  ('paper plane',      'paper plane',     'seed'),
  ('penicillin',       'penicillin',      'seed'),
  ('jungle bird',      'jungle bird',     'seed')
on conflict do nothing;
