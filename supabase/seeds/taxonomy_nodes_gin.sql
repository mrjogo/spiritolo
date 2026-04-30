-- Gin sub-styles.
-- Type-level cluster: each style is a definitional category in cocktail
-- recipes (London Dry vs Old Tom vs Plymouth vs Genever produce
-- substantially different drinks even at the same proportions). London Dry
-- is EU-regulated; Plymouth has a 2015 geographical indication granted to
-- Plymouth Gin Distillery; Old Tom is a historical sweetened style with no
-- legal definition; Genever is the malt-wine-based Dutch progenitor.
update taxonomy_nodes set role_default = 'base_spirit' where slug = 'gin';

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('london_dry_gin', 'London Dry Gin', true, 'base_spirit'),
  ('old_tom_gin',    'Old Tom Gin',    true, 'base_spirit'),
  ('plymouth_gin',   'Plymouth Gin',   true, 'base_spirit'),
  ('genever',        'Genever',        true, 'base_spirit');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('gin', 'london_dry_gin'),
  ('gin', 'old_tom_gin'),
  ('gin', 'plymouth_gin'),
  ('gin', 'genever')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. Bare 'gin' stays unaliased so
-- recipes specifying just "gin" land on the family parent and surface as
-- underspecified — bartenders treat London Dry as the cocktail default but
-- some recipes (Tom Collins, Martinez) historically called for Old Tom and
-- the audit pass should flag these.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('london dry',     'london_dry_gin'),
  ('london dry gin', 'london_dry_gin'),
  ('old tom',        'old_tom_gin'),
  ('old tom gin',    'old_tom_gin'),
  ('plymouth',       'plymouth_gin'),
  ('plymouth gin',   'plymouth_gin'),
  ('jenever',        'genever'),
  ('dutch gin',      'genever'),
  ('hollands',       'genever'),
  ('hollands gin',   'genever')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
