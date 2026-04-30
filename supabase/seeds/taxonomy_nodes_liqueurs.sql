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
