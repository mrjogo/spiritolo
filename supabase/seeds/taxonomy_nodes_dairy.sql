-- Dairy and egg.
-- Type-level cluster: cream, milk, half_and_half, condensed_milk, egg_white.
-- Heavy cream and whipping cream are largely interchangeable in cocktails
-- (the difference is fat content — heavy ≥36%, whipping 30-35%); both
-- alias to the `cream` cluster. Recipes calling out specifically heavy
-- vs whipping can be modeled as expressions in a follow-up if needed.
--
-- role_default = 'other' for the dairy products. The dedup spec's role
-- vocabulary doesn't include a 'dairy' role; 'other' is the catch-all.
-- Egg white is unique (used as a foam agent) but also gets 'other' since
-- the dedup spec doesn't define a foam-agent role.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('dairy', 'Dairy', 'other');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('cream',          'Cream',                  true, 'other'),
  ('milk',           'Milk',                   true, 'other'),
  ('half_and_half',  'Half-and-Half',          true, 'other'),
  ('condensed_milk', 'Sweetened Condensed Milk', true, 'other'),
  ('egg_white',      'Egg White',              true, 'other');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('dairy', 'cream'),
  ('dairy', 'milk'),
  ('dairy', 'half_and_half'),
  ('dairy', 'condensed_milk'),
  ('dairy', 'egg_white')  -- egg_white parented under dairy for navigational simplicity
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms. Heavy and whipping cream cluster
-- together as 'cream' (interchangeable in cocktail recipes; fat-content
-- differences don't change drink identity at the joint-key level).
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('heavy cream',                  'cream'),
  ('whipping cream',               'cream'),
  ('heavy whipping cream',         'cream'),
  ('double cream',                 'cream'),
  ('whole milk',                   'milk'),
  ('half and half',                'half_and_half'),
  ('half-n-half',                  'half_and_half'),
  ('condensed milk',               'condensed_milk'),
  ('sweetened condensed milk',     'condensed_milk'),
  ('egg whites',                   'egg_white'),
  ('one egg white',                'egg_white')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
