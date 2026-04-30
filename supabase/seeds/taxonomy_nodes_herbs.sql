-- Fresh herbs and produce used in cocktails (muddled, juiced, garnished).
-- Type-level cluster: each herb / produce item is a distinct cocktail-
-- identity ingredient. A Mojito with mint vs basil is fundamentally a
-- different drink even though both follow the same template.
--
-- role_default = 'other' across — the dedup spec's role vocabulary doesn't
-- have a 'fresh' or 'muddle' role; 'other' is the catch-all. Mint is also
-- often a 'garnish' on top, but the muddle (which carries the cluster
-- weight) makes 'other' the safer default; the role classifier's
-- contextual rules can promote based on amount/position.
--
-- `ginger` is the fresh root, distinct from ginger_beer / ginger_ale (in
-- the mixers family) and ginger_syrup (would go in syrups if added).
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('fresh_produce', 'Fresh Produce', 'other');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('mint',     'Mint',     true, 'other'),
  ('basil',    'Basil',    true, 'other'),
  ('ginger',   'Ginger',   true, 'other'),
  ('cucumber', 'Cucumber', true, 'other'),
  ('jalapeno', 'Jalapeño', true, 'other');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('fresh_produce', 'mint'),
  ('fresh_produce', 'basil'),
  ('fresh_produce', 'ginger'),
  ('fresh_produce', 'cucumber'),
  ('fresh_produce', 'jalapeno')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('mint leaves',        'mint'),
  ('fresh mint',         'mint'),
  ('mint sprig',         'mint'),
  ('mint sprigs',        'mint'),
  ('spearmint',          'mint'),
  ('fresh basil',        'basil'),
  ('basil leaves',       'basil'),
  ('fresh ginger',       'ginger'),
  ('ginger root',        'ginger'),
  ('fresh cucumber',     'cucumber'),
  ('cucumber slices',    'cucumber'),
  ('jalapeño',           'jalapeno'),
  ('jalapeño pepper',    'jalapeno'),
  ('jalapeno pepper',    'jalapeno'),
  ('fresh jalapeno',     'jalapeno')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
