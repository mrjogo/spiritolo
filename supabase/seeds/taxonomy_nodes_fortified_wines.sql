-- Fortified wines.
-- Top-level family `fortified_wine` covers wine-based products that are
-- fortified, aromatized, or both: sherry, port, madeira, and the aperitif-
-- wine bucket (Lillet, Cocchi). Vermouth keeps its own top-level family
-- because it predates this seed and is structurally already a peer.
--
-- Mixed antichain:
--   * Type-level cluster for sherry/port/madeira styles — each style is a
--     distinct substance category in cocktail recipes (Fino vs Oloroso vs
--     PX behave very differently). Brands roll up via expressions.
--   * Brand-as-substance for Lillet (each color) and Cocchi Americano per
--     the dedup spec carve-out — cocktail vocabulary names them as
--     substance.
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('fortified_wine', 'Fortified Wine', 'modifier');

-- Sub-family parents (non-cluster).
insert into taxonomy_nodes (slug, display_name, role_default) values
  ('sherry',         'Sherry',          'modifier'),
  ('port',           'Port',            'modifier'),
  ('madeira',        'Madeira',         'modifier'),
  ('aperitif_wine',  'Aperitif Wine',   'modifier');

-- Sherry style cluster nodes.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('fino_sherry',         'Fino Sherry',         true, 'modifier'),
  ('manzanilla_sherry',   'Manzanilla Sherry',   true, 'modifier'),
  ('amontillado_sherry',  'Amontillado Sherry',  true, 'modifier'),
  ('oloroso_sherry',      'Oloroso Sherry',      true, 'modifier'),
  ('palo_cortado_sherry', 'Palo Cortado Sherry', true, 'modifier'),
  ('pedro_ximenez',       'Pedro Ximénez Sherry', true, 'modifier');

-- Port style cluster nodes.
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('ruby_port',    'Ruby Port',    true, 'modifier'),
  ('tawny_port',   'Tawny Port',   true, 'modifier'),
  ('white_port',   'White Port',   true, 'modifier'),
  ('vintage_port', 'Vintage Port', true, 'modifier');

-- Madeira style cluster nodes (driest to sweetest).
insert into taxonomy_nodes (slug, display_name, is_cluster_node, role_default) values
  ('sercial_madeira',  'Sercial Madeira',  true, 'modifier'),
  ('verdelho_madeira', 'Verdelho Madeira', true, 'modifier'),
  ('bual_madeira',     'Bual Madeira',     true, 'modifier'),
  ('malmsey_madeira',  'Malmsey Madeira',  true, 'modifier');

-- Brand nodes (top-level, no parent).
insert into taxonomy_nodes (slug, display_name, role) values
  ('lillet', 'Lillet', 'brand'),  -- Pernod Ricard (brand est. 1872; quinquina form was Kina Lillet until 1986 reformulation)
  ('cocchi', 'Cocchi', 'brand');  -- Giulio Cocchi (Asti, 1891); owned by Bava Family since 1978

-- Brand-as-substance expression cluster nodes.
insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  ('lillet_blanc',     'Lillet Blanc',     'expression', true, 'modifier'),
  ('lillet_rose',      'Lillet Rosé',      'expression', true, 'modifier'),
  ('lillet_rouge',     'Lillet Rouge',     'expression', true, 'modifier'),
  ('cocchi_americano', 'Cocchi Americano', 'expression', true, 'modifier');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  -- sub-families under fortified_wine
  ('fortified_wine', 'sherry'),
  ('fortified_wine', 'port'),
  ('fortified_wine', 'madeira'),
  ('fortified_wine', 'aperitif_wine'),
  -- sherry styles under sherry
  ('sherry', 'fino_sherry'),
  ('sherry', 'manzanilla_sherry'),
  ('sherry', 'amontillado_sherry'),
  ('sherry', 'oloroso_sherry'),
  ('sherry', 'palo_cortado_sherry'),
  ('sherry', 'pedro_ximenez'),
  -- port styles under port
  ('port', 'ruby_port'),
  ('port', 'tawny_port'),
  ('port', 'white_port'),
  ('port', 'vintage_port'),
  -- madeira styles under madeira
  ('madeira', 'sercial_madeira'),
  ('madeira', 'verdelho_madeira'),
  ('madeira', 'bual_madeira'),
  ('madeira', 'malmsey_madeira'),
  -- aperitif_wine brand-as-substance expressions: dual-parent [brand, aperitif_wine]
  ('lillet',         'lillet_blanc'),
  ('aperitif_wine',  'lillet_blanc'),
  ('lillet',         'lillet_rose'),
  ('aperitif_wine',  'lillet_rose'),
  ('lillet',         'lillet_rouge'),
  ('aperitif_wine',  'lillet_rouge'),
  ('cocchi',         'cocchi_americano'),
  ('aperitif_wine',  'cocchi_americano')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. Generic 'sherry', 'port', 'madeira'
-- are intentionally NOT aliased — recipes saying those alone are
-- underspecified between styles and should surface as such.
-- 'kina lillet' routes to lillet_blanc per modern bartender convention
-- (the historical quinine-fortified Kina Lillet was discontinued in 1986;
-- modern Lillet Blanc is the closest surviving product, though Cocchi
-- Americano is often considered the better quinine-bitter substitute).
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  -- sherry shorthands
  ('fino',                'fino_sherry'),
  ('manzanilla',          'manzanilla_sherry'),
  ('amontillado',         'amontillado_sherry'),
  ('oloroso',             'oloroso_sherry'),
  ('palo cortado',        'palo_cortado_sherry'),
  ('pedro ximenez',       'pedro_ximenez'),
  ('pedro ximénez',       'pedro_ximenez'),
  ('px',                  'pedro_ximenez'),
  ('p.x.',                'pedro_ximenez'),
  ('px sherry',           'pedro_ximenez'),
  -- madeira shorthands
  ('sercial',             'sercial_madeira'),
  ('verdelho',            'verdelho_madeira'),
  ('bual',                'bual_madeira'),
  ('boal',                'bual_madeira'),  -- alternate spelling
  ('malmsey',             'malmsey_madeira'),
  -- aperitif wine shorthands
  ('lillet',              'lillet_blanc'),
  ('kina lillet',         'lillet_blanc'),
  ('aperitivo americano', 'cocchi_americano'),
  ('cocchi aperitivo americano', 'cocchi_americano')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
