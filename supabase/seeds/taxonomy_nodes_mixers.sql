-- Mixers (carbonated and bottled).
-- Type-level cluster: each mixer is a distinct cocktail-identity substance.
-- Brands roll up via expressions (none seeded yet — D's mapper auto-creates
-- when recipes call out Fever-Tree, Schweppes, Goslings, Coca-Cola, etc.).
--
-- Role defaults:
--   * 'dilution' for soda_water and tonic_water — these primarily dilute
--     the drink (G&T uses tonic as a stretching agent; Highball uses soda).
--   * 'modifier' for ginger_beer, ginger_ale, cola, lemonade — these add
--     flavor and sugar substantively, not just dilution.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('mixer', 'Mixer', 'dilution');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('soda_water',  'Soda Water',  true, 'dilution'),
  ('tonic_water', 'Tonic Water', true, 'dilution'),
  ('ginger_beer', 'Ginger Beer', true, 'modifier'),
  ('ginger_ale',  'Ginger Ale',  true, 'modifier'),
  ('cola',        'Cola',        true, 'modifier'),
  ('lemonade',    'Lemonade',    true, 'modifier');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('mixer', 'soda_water'),
  ('mixer', 'tonic_water'),
  ('mixer', 'ginger_beer'),
  ('mixer', 'ginger_ale'),
  ('mixer', 'cola'),
  ('mixer', 'lemonade')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('club soda',       'soda_water'),
  ('seltzer',         'soda_water'),
  ('seltzer water',   'soda_water'),
  ('sparkling water', 'soda_water'),
  ('soda',            'soda_water'),
  ('tonic',           'tonic_water'),
  ('coke',            'cola'),
  ('coca-cola',       'cola'),
  ('coca cola',       'cola'),
  ('pepsi',           'cola')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
