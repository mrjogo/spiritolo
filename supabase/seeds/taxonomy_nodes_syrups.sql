-- Syrups.
-- Type-level cluster: each syrup category is its own cocktail-identity
-- substance. Brands roll up via expressions (none seeded yet — D's mapper
-- can auto-create when recipes call out specific brands like Velvet
-- Falernum, BG Reynolds, Liber, Small Hand Foods).
--
-- Notable details verified via web research:
--   * Falernum: John D. Taylor's Velvet Falernum is the Barbados original
--     (R.L. Seale & Co., late 1800s); BG Reynolds, Hamilton, and others
--     are modern alternatives.
--   * Orgeat: BG Reynolds (Portland), Liber & Co., Small Hand Foods,
--     Latitude 29 are the craft brands.
--   * Grenadine: pomegranate-based; many commercial brands (e.g. Rose's)
--     substitute high-fructose corn syrup with artificial color and
--     flavor — Liber & Co., BG Reynolds, Master of Mixes are real-fruit
--     alternatives.
insert into taxonomy_nodes (slug, display_name, default_role) values
  ('syrup', 'Syrup', 'sweetener');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('simple_syrup',   'Simple Syrup',   true, 'sweetener'),
  ('demerara_syrup', 'Demerara Syrup', true, 'sweetener'),
  ('honey_syrup',    'Honey Syrup',    true, 'sweetener'),
  ('agave_syrup',    'Agave Syrup',    true, 'sweetener'),
  ('grenadine',      'Grenadine',      true, 'sweetener'),
  ('falernum',       'Falernum',       true, 'sweetener'),
  ('orgeat',         'Orgeat',         true, 'sweetener');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('syrup', 'simple_syrup'),
  ('syrup', 'demerara_syrup'),
  ('syrup', 'honey_syrup'),
  ('syrup', 'agave_syrup'),
  ('syrup', 'grenadine'),
  ('syrup', 'falernum'),
  ('syrup', 'orgeat')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('sugar syrup',        'simple_syrup'),
  ('1:1 simple',         'simple_syrup'),
  ('rich simple syrup',  'demerara_syrup'),  -- 2:1 demerara is often called 'rich simple'
  ('rich syrup',         'demerara_syrup'),
  ('demerara',           'demerara_syrup'),
  ('honey',              'honey_syrup'),
  ('agave',              'agave_syrup'),
  ('agave nectar',       'agave_syrup'),
  ('pomegranate syrup',  'grenadine'),
  ('velvet falernum',    'falernum'),
  ('almond syrup',       'orgeat')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
