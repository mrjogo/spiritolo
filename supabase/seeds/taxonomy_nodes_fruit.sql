-- Fruit produce parents and juice form-nodes (consolidated).
-- Replaces both `taxonomy_nodes_juices.sql` and the `_01_produce.sql` from
-- the base-spirits split. One canonical place for fruit and the juice
-- forms derived from them.
--
-- Structure:
--   * citrus (parent) → lemon / lime / orange / grapefruit (children)
--   * pineapple, cranberry are top-level (not citrus)
--   * juice form-nodes (lemon_juice, etc.) are CLUSTER identities,
--     parented to their produce node
--
-- The JUICE forms are the cluster identities, not the produce parents.
-- Recipes specifying just "lemon" without "juice" land on the produce
-- node and surface as underspecified — most recipe text means juice
-- when it says "lemon", but muddled-fruit drinks (Old Cuban) genuinely
-- need the produce form, so the underspecified flag is intentional.
--
-- role_default values:
--   * Citrus juices: 'citrus' (per dedup spec).
--   * Non-citrus juices (pineapple, cranberry): 'modifier' — they
--     contribute substantively to drink character (Piña Colada,
--     Cosmopolitan) rather than just stretching with sour.

-- Produce parents.
insert into taxonomy_nodes (slug, display_name) values
  ('citrus',     'Citrus'),
  ('lemon',      'Lemon'),
  ('lime',       'Lime'),
  ('orange',     'Orange'),
  ('grapefruit', 'Grapefruit'),
  ('pineapple',  'Pineapple'),
  ('cranberry',  'Cranberry');

-- Citrus children under the citrus parent.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('citrus', 'lemon'),
  ('citrus', 'lime'),
  ('citrus', 'orange'),
  ('citrus', 'grapefruit')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Juice form-node cluster identities.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('lemon_juice',      'Lemon Juice',      true, 'citrus'),
  ('lime_juice',       'Lime Juice',       true, 'citrus'),
  ('orange_juice',     'Orange Juice',     true, 'citrus'),
  ('grapefruit_juice', 'Grapefruit Juice', true, 'citrus'),
  ('pineapple_juice',  'Pineapple Juice',  true, 'modifier'),
  ('cranberry_juice',  'Cranberry Juice',  true, 'modifier');

-- Each juice form-node parented to its produce node.
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

-- Aliases: cocktail-vocabulary forms for the juice form-nodes.
-- 'fresh' / 'freshly squeezed' route to the same form-node — freshness
-- is a quality attribute, not a substance distinction.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('fresh lemon juice',                'lemon_juice'),
  ('freshly squeezed lemon juice',     'lemon_juice'),
  ('lemon juice fresh',                'lemon_juice'),
  ('fresh lime juice',                 'lime_juice'),
  ('freshly squeezed lime juice',      'lime_juice'),
  ('lime juice fresh',                 'lime_juice'),
  ('fresh orange juice',               'orange_juice'),
  ('freshly squeezed orange juice',    'orange_juice'),
  ('oj',                               'orange_juice'),
  ('fresh grapefruit juice',           'grapefruit_juice'),
  ('freshly squeezed grapefruit juice','grapefruit_juice'),
  ('fresh pineapple juice',            'pineapple_juice'),
  ('fresh cranberry juice',            'cranberry_juice')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
