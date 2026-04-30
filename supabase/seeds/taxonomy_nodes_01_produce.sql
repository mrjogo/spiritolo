-- Citrus produce parent nodes (loads second per the `01_` numeric prefix).
-- These are the structural parents for the juice form-nodes seeded in
-- taxonomy_nodes_juices.sql (lemon_juice, lime_juice, orange_juice,
-- grapefruit_juice). The produce nodes are NOT cluster identities —
-- the JUICE forms are. A recipe specifying "lemon" without "juice"
-- lands on the produce node and surfaces as underspecified (most
-- recipes mean lemon juice when they say "lemon", but the form
-- distinction matters for muddled-fruit drinks like the Old Cuban).
--
-- citrus is a category whose children share substitution semantics
-- (lemon ↔ lime in many recipes; orange ↔ grapefruit less commonly).
-- Per the lean stance, no further produce categories beyond citrus
-- until a real consumer surface (filter chip, browse section) demands
-- them.

insert into taxonomy_nodes (slug, display_name) values
  ('citrus',     'Citrus'),
  ('lemon',      'Lemon'),
  ('lime',       'Lime'),
  ('orange',     'Orange'),
  ('grapefruit', 'Grapefruit');

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
