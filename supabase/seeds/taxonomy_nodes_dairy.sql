-- Dairy and egg.
-- Type-level cluster: cream, milk, half_and_half, condensed_milk, plus
-- whole egg and its split forms (white, yolk). Heavy cream and whipping
-- cream are largely interchangeable in cocktails (the difference is fat
-- content — heavy ≥36%, whipping 30-35%); both alias to the `cream`
-- cluster. Recipes calling out specifically heavy vs whipping can be
-- modeled as expressions in a follow-up if needed.
--
-- Whole egg vs egg white vs egg yolk are kept as separate clusters
-- because they substantively change drink identity: a Pisco Sour with
-- whole egg vs egg white only is a different drink; flips (Brandy Flip,
-- Porto Flip) are defined by the whole egg; egg yolk is the base of
-- traditional Pisco Sour and some classic flips.
--
-- role_default = 'other' across — the dedup spec's role vocabulary
-- doesn't include 'dairy' or 'foam_agent'; 'other' is the catch-all.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('dairy', 'Dairy', 'other');

insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('cream',          'Cream',                    true, 'other'),
  ('milk',           'Milk',                     true, 'other'),
  ('half_and_half',  'Half-and-Half',            true, 'other'),
  ('condensed_milk', 'Sweetened Condensed Milk', true, 'other'),
  ('whole_egg',      'Whole Egg',                true, 'other'),
  ('egg_white',      'Egg White',                true, 'other'),
  ('egg_yolk',       'Egg Yolk',                 true, 'other');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('dairy', 'cream'),
  ('dairy', 'milk'),
  ('dairy', 'half_and_half'),
  ('dairy', 'condensed_milk'),
  -- eggs parented under dairy for navigational simplicity (recipes group
  -- them with milk/cream as texture/body ingredients in flips, fizzes,
  -- sours, eggnog).
  ('dairy', 'whole_egg'),
  ('dairy', 'egg_white'),
  ('dairy', 'egg_yolk')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms. Heavy and whipping cream cluster
-- together as 'cream' (interchangeable in cocktail recipes; fat-content
-- differences don't change drink identity at the joint-key level).
-- Bare 'egg' resolves to whole_egg per recipe convention (when a drink
-- needs a split form the recipe specifies "egg white" / "egg yolk").
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
  ('egg',                          'whole_egg'),
  ('whole egg',                    'whole_egg'),
  ('one egg',                      'whole_egg'),
  ('one whole egg',                'whole_egg'),
  ('egg whites',                   'egg_white'),
  ('one egg white',                'egg_white'),
  ('egg yolks',                    'egg_yolk'),
  ('one egg yolk',                 'egg_yolk'),
  ('yolk',                         'egg_yolk')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
