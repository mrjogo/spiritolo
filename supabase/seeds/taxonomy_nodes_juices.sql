-- Juices.
-- Form-node cluster identities. Citrus juices map to the dedup spec's
-- 'citrus' role; pineapple and cranberry are non-citrus modifiers.
-- Each juice node is parented to its produce node when an existing
-- produce parent exists (lemon, lime, orange, grapefruit are already
-- under the citrus family); pineapple and cranberry get new produce
-- parents added here.

-- New produce parents for non-citrus juices.
insert into taxonomy_nodes (slug, display_name) values
  ('pineapple', 'Pineapple'),
  ('cranberry', 'Cranberry');

-- Juice form-node cluster nodes.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('lemon_juice',      'Lemon Juice',      true, 'citrus'),
  ('lime_juice',       'Lime Juice',       true, 'citrus'),
  ('orange_juice',     'Orange Juice',     true, 'citrus'),
  ('grapefruit_juice', 'Grapefruit Juice', true, 'citrus'),
  ('pineapple_juice',  'Pineapple Juice',  true, 'modifier'),
  ('cranberry_juice',  'Cranberry Juice',  true, 'modifier');

-- Edges: each juice form-node parented to its produce node.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('lemon',      'lemon_juice'),
  ('lime',       'lime_juice'),
  ('orange',     'orange_juice'),
  ('grapefruit', 'grapefruit_juice'),
  ('pineapple',  'pineapple_juice'),
  ('cranberry',  'cranberry_juice')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms. Recipe text often uses 'fresh
-- lemon juice' or 'freshly squeezed lemon juice' — these all route to
-- the same form-node since freshness is a quality attribute, not a
-- substance distinction.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('fresh lemon juice',           'lemon_juice'),
  ('freshly squeezed lemon juice','lemon_juice'),
  ('lemon juice fresh',           'lemon_juice'),
  ('fresh lime juice',            'lime_juice'),
  ('freshly squeezed lime juice', 'lime_juice'),
  ('lime juice fresh',            'lime_juice'),
  ('fresh orange juice',          'orange_juice'),
  ('freshly squeezed orange juice','orange_juice'),
  ('oj',                          'orange_juice'),
  ('fresh grapefruit juice',      'grapefruit_juice'),
  ('freshly squeezed grapefruit juice','grapefruit_juice'),
  ('fresh pineapple juice',       'pineapple_juice'),
  ('fresh cranberry juice',       'cranberry_juice')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
