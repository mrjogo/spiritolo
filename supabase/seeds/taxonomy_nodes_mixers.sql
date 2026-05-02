-- Mixers (carbonated and bottled).
-- Type-level cluster: each mixer is a distinct cocktail-identity substance.
-- Brands roll up via expressions (none seeded yet — D's mapper auto-creates
-- when recipes call out Fever-Tree, Schweppes, Goslings, Coca-Cola, etc.).
--
-- Role defaults:
--   * 'dilution' for soda_water only — pure carbonated water, no flavor,
--     genuinely a stretching agent.
--   * 'modifier' for tonic_water, ginger_beer, ginger_ale, cola, lemonade
--     — these all carry meaningful flavor and sugar that substantively
--     shape the drink's character. A Moscow Mule is "vodka + ginger
--     beer," not "vodka diluted with ginger beer"; a G&T is defined by
--     the bitter quinine, not by water-stretching the gin. Cocktail-
--     functionally these behave the same way Campari or vermouth does
--     in their drinks — they ARE the modifying flavor, not dilution.
insert into taxonomy_nodes (slug, display_name, default_role) values
  ('mixer', 'Mixer', 'modifier');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('soda_water',  'Soda Water',  true, 'dilution'),
  ('tonic_water', 'Tonic Water', true, 'modifier'),
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
