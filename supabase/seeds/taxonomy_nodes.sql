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
