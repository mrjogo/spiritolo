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

-- Brand nodes. Brands are top-level (no parent) because they span categories:
-- Fee Brothers makes amaretto syrup, Angostura makes rum, Bittermens makes
-- tonic syrup, etc. Parenting a brand under any single category would imply a
-- constraint on what they make. Each expression carries the type parent
-- itself; the brand parent is just provenance.
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
  -- expressions: dual-parent [brand, type]. Brand provides provenance;
  -- type provides the cluster_node ancestor for rollup.
  ('angostura',                       'angostura_aromatic_bitters'),
  ('angostura_style_aromatic_bitters','angostura_aromatic_bitters'),
  ('angostura',                       'angostura_orange_bitters'),
  ('orange_bitters',                  'angostura_orange_bitters'),
  ('peychauds',                       'peychauds_bitters'),
  ('creole_bitters',                  'peychauds_bitters'),
  ('regans',                          'regans_orange_bitters'),
  ('orange_bitters',                  'regans_orange_bitters'),
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

-- Amari.
-- Brand-as-substance applies across the family: each major amaro is its own
-- cluster identity at the expression level because cocktail vocabulary names
-- each as a substance ("a Cynar", "Campari", "Fernet"), not as a generic
-- class. No broader type meaningfully groups them — Campari, Cynar, and
-- Fernet-Branca are radically different flavor profiles even though all are
-- technically amari. The amaro family parent stays non-cluster; recipes
-- specifying generic "amaro" surface as underspecified in the dedup audit.
--
-- Brand nodes float at the top level (no parent); expressions are parented
-- to [brand, amaro]. For eponymous products with no bottle descriptor
-- (Campari, Aperol, Cynar), the expression slug appends the family-parent
-- slug (`_amaro`) to disambiguate from the brand slug. Display name stays
-- the bottle name.
update taxonomy_nodes set role_default = 'modifier' where slug = 'amaro';

-- Brand nodes (top-level, no parent — brands span categories).
insert into taxonomy_nodes (slug, display_name, role) values
  ('campari',     'Campari',         'brand'),  -- Davide Campari-Milano N.V.
  ('aperol',      'Aperol',          'brand'),  -- originally Barbieri (Padua, 1919); now Campari Group
  ('cynar',       'Cynar',           'brand'),  -- originally Pezziol; now Campari Group
  ('branca',      'Branca',          'brand'),  -- Fratelli Branca Distillerie (Milan, 1845)
  ('montenegro',  'Montenegro',      'brand'),  -- Gruppo Montenegro (Bologna, 1885)
  ('nonino',      'Nonino',          'brand'),  -- Nonino Distillatori (Friuli)
  ('averna',      'Averna',          'brand'),  -- originally Fratelli Averna (Sicily, 1868); now Campari Group
  ('meletti',     'Meletti',         'brand'),  -- Meletti (Ascoli Piceno, 1870)
  ('lucano',      'Lucano',          'brand'),  -- Amaro Lucano S.p.A. (Pisticci, Basilicata)
  ('ramazzotti',  'Ramazzotti',      'brand'),  -- originally Ramazzotti (Milan, 1815); now Pernod Ricard
  ('paolucci',    'Paolucci',        'brand'),  -- Paolucci (Sora, Lazio, 1873) — makes Amaro Ciociaro
  ('braulio',     'Braulio',         'brand'),  -- Cantine Peloni (Bormio); now Caffo Group
  ('bosca',       'Bosca',           'brand');  -- Bosca / Tosti (Canelli, Piemonte) — makes Cardamaro

insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  -- Major amari named in the dedup spec.
  ('campari_amaro',    'Campari',                    'expression', true, 'modifier'),
  ('aperol_amaro',     'Aperol',                     'expression', true, 'modifier'),
  ('cynar_amaro',      'Cynar',                      'expression', true, 'modifier'),
  ('fernet_branca',    'Fernet-Branca',              'expression', true, 'modifier'),
  ('amaro_montenegro', 'Amaro Montenegro',           'expression', true, 'modifier'),
  ('amaro_nonino',     'Amaro Nonino Quintessentia', 'expression', true, 'modifier'),
  -- Long tail commonly seen in cocktail recipes.
  ('amaro_averna',     'Amaro Averna',               'expression', true, 'modifier'),
  ('amaro_meletti',    'Amaro Meletti',              'expression', true, 'modifier'),
  ('amaro_lucano',     'Amaro Lucano',               'expression', true, 'modifier'),
  ('amaro_ramazzotti', 'Amaro Ramazzotti',           'expression', true, 'modifier'),
  ('amaro_ciociaro',   'Amaro Ciociaro',             'expression', true, 'modifier'),
  ('amaro_braulio',    'Amaro Braulio',              'expression', true, 'modifier'),
  ('cardamaro',        'Cardamaro Vino Amaro',       'expression', true, 'modifier');

-- Edges: each expression dual-parented to [brand, amaro family].
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('amaro',         'campari_amaro'),
  ('campari',       'campari_amaro'),
  ('amaro',         'aperol_amaro'),
  ('aperol',        'aperol_amaro'),
  ('amaro',         'cynar_amaro'),
  ('cynar',         'cynar_amaro'),
  ('amaro',         'fernet_branca'),
  ('branca',        'fernet_branca'),
  ('amaro',         'amaro_montenegro'),
  ('montenegro',    'amaro_montenegro'),
  ('amaro',         'amaro_nonino'),
  ('nonino',        'amaro_nonino'),
  ('amaro',         'amaro_averna'),
  ('averna',        'amaro_averna'),
  ('amaro',         'amaro_meletti'),
  ('meletti',       'amaro_meletti'),
  ('amaro',         'amaro_lucano'),
  ('lucano',        'amaro_lucano'),
  ('amaro',         'amaro_ramazzotti'),
  ('ramazzotti',    'amaro_ramazzotti'),
  ('amaro',         'amaro_ciociaro'),
  ('paolucci',      'amaro_ciociaro'),
  ('amaro',         'amaro_braulio'),
  ('braulio',       'amaro_braulio'),
  ('amaro',         'cardamaro'),
  ('bosca',         'cardamaro')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. The eponymous shorthands
-- ('campari', 'aperol', 'cynar', 'fernet') resolve to the expression node
-- (the cluster identity) rather than the brand node, matching cocktail
-- vocabulary intent.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('campari',                    'campari_amaro'),
  ('aperol',                     'aperol_amaro'),
  ('cynar',                      'cynar_amaro'),
  ('fernet',                     'fernet_branca'),
  ('fernet branca',              'fernet_branca'),
  ('montenegro',                 'amaro_montenegro'),
  ('nonino',                     'amaro_nonino'),
  ('amaro nonino',               'amaro_nonino'),
  ('averna',                     'amaro_averna'),
  ('meletti',                    'amaro_meletti'),
  ('lucano',                     'amaro_lucano'),
  ('ramazzotti',                 'amaro_ramazzotti'),
  ('ciociaro',                   'amaro_ciociaro'),
  ('cio ciaro',                  'amaro_ciociaro'),
  ('amaro cio ciaro',            'amaro_ciociaro'),
  ('amaro ciociaro',             'amaro_ciociaro'),
  ('paolucci amaro ciociaro',    'amaro_ciociaro'),
  ('braulio',                    'amaro_braulio'),
  ('cardamaro',                  'cardamaro')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
