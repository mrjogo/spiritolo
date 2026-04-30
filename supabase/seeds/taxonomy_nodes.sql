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

-- Liqueurs / cordials.
-- Mixed antichain: type-level cluster for substances where many brands
-- substitute (maraschino, triple sec, crème de violette, crème de cassis);
-- brand-as-substance for items where a single brand defines the substance
-- (Chartreuse green/yellow, Bénédictine, Drambuie, Pimm's No. 1, Suze).
-- The family parent `liqueur` stays non-cluster.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('liqueur', 'Liqueur', 'modifier');

-- Type cluster nodes (broad substance categories with many interchangeable brands).
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('maraschino_liqueur', 'Maraschino Liqueur', true, 'modifier'),
  ('triple_sec',         'Triple Sec',         true, 'modifier'),  -- broader "orange liqueur"; Cointreau, Combier, Grand Marnier roll up
  ('creme_de_violette',  'Crème de Violette',  true, 'modifier'),
  ('creme_de_cassis',    'Crème de Cassis',    true, 'modifier');

-- Brand nodes (top-level, no parent).
insert into taxonomy_nodes (slug, display_name, role) values
  ('luxardo',     'Luxardo',     'brand'),  -- Luxardo (Torreglia, Italy; originally Zara/Zadar 1821)
  ('chartreuse',  'Chartreuse',  'brand'),  -- Chartreuse Diffusion S.A.S. / Carthusian monks (since 1737)
  ('cointreau',   'Cointreau',   'brand'),  -- Rémy Cointreau (Angers, France; merged 1990)
  ('benedictine', 'Bénédictine', 'brand'),  -- Distillerie Bénédictine S.A. (Fécamp, Normandy; recipe 1510)
  ('drambuie',    'Drambuie',    'brand'),  -- William Grant & Sons (since 2014)
  ('pimms',       'Pimm''s',     'brand'),  -- Diageo (since 1997; brand est. 1823)
  ('suze',        'Suze',        'brand');  -- Pernod Ricard (since 1965; brand est. 1889)

-- Brand-as-substance expression cluster nodes.
-- Per dedup spec carve-out: each is its own cluster identity because cocktail
-- vocabulary names them as substance (recipes say "Bénédictine", "Drambuie",
-- "Suze", not "a French herbal liqueur").
insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  ('green_chartreuse',  'Green Chartreuse',     'expression', true, 'modifier'),
  ('yellow_chartreuse', 'Yellow Chartreuse',    'expression', true, 'modifier'),
  ('benedictine_dom',   'Bénédictine D.O.M.',   'expression', true, 'modifier'),
  ('drambuie_liqueur',  'Drambuie',             'expression', true, 'modifier'),
  ('pimms_no_1_cup',    'Pimm''s No. 1 Cup',    'expression', true, 'modifier'),
  ('suze_liqueur',      'Suze',                 'expression', true, 'modifier');

-- Non-cluster expressions (roll up to type cluster).
insert into taxonomy_nodes (slug, display_name, role, role_default) values
  ('luxardo_maraschino_originale', 'Luxardo Maraschino Originale', 'expression', 'modifier'),
  ('cointreau_triple_sec',         'Cointreau',                    'expression', 'modifier');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  -- type clusters under liqueur family
  ('liqueur', 'maraschino_liqueur'),
  ('liqueur', 'triple_sec'),
  ('liqueur', 'creme_de_violette'),
  ('liqueur', 'creme_de_cassis'),
  -- brand-as-substance cluster expressions parented to [brand, liqueur family]
  ('chartreuse',  'green_chartreuse'),
  ('liqueur',     'green_chartreuse'),
  ('chartreuse',  'yellow_chartreuse'),
  ('liqueur',     'yellow_chartreuse'),
  ('benedictine', 'benedictine_dom'),
  ('liqueur',     'benedictine_dom'),
  ('drambuie',    'drambuie_liqueur'),
  ('liqueur',     'drambuie_liqueur'),
  ('pimms',       'pimms_no_1_cup'),
  ('liqueur',     'pimms_no_1_cup'),
  ('suze',        'suze_liqueur'),
  ('liqueur',     'suze_liqueur'),
  -- non-cluster expressions parented to [brand, type cluster]
  ('luxardo',            'luxardo_maraschino_originale'),
  ('maraschino_liqueur', 'luxardo_maraschino_originale'),
  ('cointreau',          'cointreau_triple_sec'),
  ('triple_sec',         'cointreau_triple_sec')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. Brand-as-substance shorthands route
-- to the expression (cluster identity); type-cluster shorthands route to the
-- type cluster. The 'chartreuse' bare alias is intentionally absent — recipes
-- specifying "Chartreuse" alone are ambiguous (green or yellow) and should
-- surface as underspecified.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('maraschino',                 'maraschino_liqueur'),
  ('maraschino liqueur',         'maraschino_liqueur'),
  ('luxardo maraschino',         'luxardo_maraschino_originale'),
  ('luxardo maraschino originale','luxardo_maraschino_originale'),
  ('triple sec',                 'triple_sec'),
  ('orange liqueur',             'triple_sec'),
  ('cointreau',                  'cointreau_triple_sec'),
  ('chartreuse verte',           'green_chartreuse'),
  ('chartreuse jaune',           'yellow_chartreuse'),
  ('violette',                   'creme_de_violette'),
  ('crème de violette',          'creme_de_violette'),
  ('cassis',                     'creme_de_cassis'),
  ('crème de cassis',            'creme_de_cassis'),
  ('benedictine',                'benedictine_dom'),
  ('bénédictine',                'benedictine_dom'),
  ('benedictine dom',            'benedictine_dom'),
  ('bénédictine d.o.m.',         'benedictine_dom'),
  ('drambuie',                   'drambuie_liqueur'),
  ('pimms',                      'pimms_no_1_cup'),
  ('pimm''s',                    'pimms_no_1_cup'),
  ('pimms no 1',                 'pimms_no_1_cup'),
  ('pimm''s no. 1',              'pimms_no_1_cup'),
  ('pimms cup',                  'pimms_no_1_cup'),
  ('pimm''s cup',                'pimms_no_1_cup'),
  ('suze',                       'suze_liqueur')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;

-- Fortified wines.
-- Top-level family `fortified_wine` covers wine-based products that are
-- fortified, aromatized, or both: sherry, port, madeira, and the aperitif-
-- wine bucket (Lillet, Cocchi). Vermouth keeps its own top-level family
-- because it predates this seed and is structurally already a peer.
--
-- Mixed antichain:
--   * Type-level cluster for sherry/port/madeira styles — each style is a
--     distinct substance category in cocktail recipes (Fino vs Oloroso vs
--     PX behave very differently). Brands roll up via expressions.
--   * Brand-as-substance for Lillet (each color) and Cocchi Americano per
--     the dedup spec carve-out — cocktail vocabulary names them as
--     substance.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('fortified_wine', 'Fortified Wine', 'modifier');

-- Sub-family parents (non-cluster).
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('sherry',         'Sherry',          'modifier'),
  ('port',           'Port',            'modifier'),
  ('madeira',        'Madeira',         'modifier'),
  ('aperitif_wine',  'Aperitif Wine',   'modifier');

-- Sherry style cluster nodes.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('fino_sherry',         'Fino Sherry',         true, 'modifier'),
  ('manzanilla_sherry',   'Manzanilla Sherry',   true, 'modifier'),
  ('amontillado_sherry',  'Amontillado Sherry',  true, 'modifier'),
  ('oloroso_sherry',      'Oloroso Sherry',      true, 'modifier'),
  ('palo_cortado_sherry', 'Palo Cortado Sherry', true, 'modifier'),
  ('pedro_ximenez',       'Pedro Ximénez Sherry', true, 'modifier');

-- Port style cluster nodes.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('ruby_port',    'Ruby Port',    true, 'modifier'),
  ('tawny_port',   'Tawny Port',   true, 'modifier'),
  ('white_port',   'White Port',   true, 'modifier'),
  ('vintage_port', 'Vintage Port', true, 'modifier');

-- Madeira style cluster nodes (driest to sweetest).
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('sercial_madeira',  'Sercial Madeira',  true, 'modifier'),
  ('verdelho_madeira', 'Verdelho Madeira', true, 'modifier'),
  ('bual_madeira',     'Bual Madeira',     true, 'modifier'),
  ('malmsey_madeira',  'Malmsey Madeira',  true, 'modifier');

-- Brand nodes (top-level, no parent).
insert into taxonomy_nodes (slug, display_name, role) values
  ('lillet', 'Lillet', 'brand'),  -- Pernod Ricard (brand est. 1872; quinquina form was Kina Lillet until 1986 reformulation)
  ('cocchi', 'Cocchi', 'brand');  -- Giulio Cocchi (Asti, 1891); owned by Bava Family since 1978

-- Brand-as-substance expression cluster nodes.
insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  ('lillet_blanc',     'Lillet Blanc',     'expression', true, 'modifier'),
  ('lillet_rose',      'Lillet Rosé',      'expression', true, 'modifier'),
  ('lillet_rouge',     'Lillet Rouge',     'expression', true, 'modifier'),
  ('cocchi_americano', 'Cocchi Americano', 'expression', true, 'modifier');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  -- sub-families under fortified_wine
  ('fortified_wine', 'sherry'),
  ('fortified_wine', 'port'),
  ('fortified_wine', 'madeira'),
  ('fortified_wine', 'aperitif_wine'),
  -- sherry styles under sherry
  ('sherry', 'fino_sherry'),
  ('sherry', 'manzanilla_sherry'),
  ('sherry', 'amontillado_sherry'),
  ('sherry', 'oloroso_sherry'),
  ('sherry', 'palo_cortado_sherry'),
  ('sherry', 'pedro_ximenez'),
  -- port styles under port
  ('port', 'ruby_port'),
  ('port', 'tawny_port'),
  ('port', 'white_port'),
  ('port', 'vintage_port'),
  -- madeira styles under madeira
  ('madeira', 'sercial_madeira'),
  ('madeira', 'verdelho_madeira'),
  ('madeira', 'bual_madeira'),
  ('madeira', 'malmsey_madeira'),
  -- aperitif_wine brand-as-substance expressions: dual-parent [brand, aperitif_wine]
  ('lillet',         'lillet_blanc'),
  ('aperitif_wine',  'lillet_blanc'),
  ('lillet',         'lillet_rose'),
  ('aperitif_wine',  'lillet_rose'),
  ('lillet',         'lillet_rouge'),
  ('aperitif_wine',  'lillet_rouge'),
  ('cocchi',         'cocchi_americano'),
  ('aperitif_wine',  'cocchi_americano')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. Generic 'sherry', 'port', 'madeira'
-- are intentionally NOT aliased — recipes saying those alone are
-- underspecified between styles and should surface as such.
-- 'kina lillet' routes to lillet_blanc per modern bartender convention
-- (the historical quinine-fortified Kina Lillet was discontinued in 1986;
-- modern Lillet Blanc is the closest surviving product, though Cocchi
-- Americano is often considered the better quinine-bitter substitute).
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  -- sherry shorthands
  ('fino',                'fino_sherry'),
  ('manzanilla',          'manzanilla_sherry'),
  ('amontillado',         'amontillado_sherry'),
  ('oloroso',             'oloroso_sherry'),
  ('palo cortado',        'palo_cortado_sherry'),
  ('pedro ximenez',       'pedro_ximenez'),
  ('pedro ximénez',       'pedro_ximenez'),
  ('px',                  'pedro_ximenez'),
  ('p.x.',                'pedro_ximenez'),
  ('px sherry',           'pedro_ximenez'),
  -- madeira shorthands
  ('sercial',             'sercial_madeira'),
  ('verdelho',            'verdelho_madeira'),
  ('bual',                'bual_madeira'),
  ('boal',                'bual_madeira'),  -- alternate spelling
  ('malmsey',             'malmsey_madeira'),
  -- aperitif wine shorthands
  ('lillet',              'lillet_blanc'),
  ('kina lillet',         'lillet_blanc'),
  ('aperitivo americano', 'cocchi_americano'),
  ('cocchi aperitivo americano', 'cocchi_americano')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
