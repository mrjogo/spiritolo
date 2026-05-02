-- Rum subtypes — rum classification is famously messy (no single axis
-- dominates — color, age, region, distillation method, and base material
-- all interact). Cluster nodes here capture the categories that recipes
-- substantively distinguish:
--   * white_rum: light, column-distilled, often filtered after brief
--     aging. Daiquiri, Mojito.
--   * dark_rum: column-distilled, aged with caramel coloring (E150a)
--     adjustment. Dark 'n Stormy, Mai Tai's float.
--   * aged_rum: column-distilled, oak-aged without caramel adjustment.
--     Old Cuban, classic punches.
--   * jamaican_rum: pot-distilled, high-ester ("hogo" / funky). Smith
--     & Cross, Hamilton 86, Wray & Nephew, Appleton. Tiki cocktails
--     (Mai Tai, Zombie, Jungle Bird).
--   * agricole_rum: French Caribbean (Martinique AOC, Guadeloupe,
--     Haiti), distilled from fresh sugarcane juice rather than
--     molasses. Rhum JM, Clément, Rhum Barbancourt. Ti' Punch,
--     Daiquiri Agricole.
--
-- Style classifications verified via Cocktail Wonk's "Six Essential
-- Tiki Rum Categories", Modern Caribbean Rum, and Wikipedia. Demerara
-- (Guyana, e.g. El Dorado), Navy (high-proof blend, e.g. Pusser's),
-- spiced (Sailor Jerry, Captain Morgan), and overproof (Wray & Nephew
-- White Overproof) are recognized cocktail-relevant categories but
-- skipped here for tightness — D's mapper auto-creates expressions
-- when recipes call them out, and curator can elevate to clusters
-- later if recipe distribution demands it.
--
-- Note: these subtypes are not strictly disjoint (an aged Jamaican
-- exists; an aged agricole exists). When recipes specify an
-- intersection, D's mapper auto-creates a more specific expression and
-- the cluster_key resolves at the dominant style.

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('white_rum',    'White Rum',     true, 'base_spirit'),
  ('dark_rum',     'Dark Rum',      true, 'base_spirit'),
  ('aged_rum',     'Aged Rum',      true, 'base_spirit'),
  ('jamaican_rum', 'Jamaican Rum',  true, 'base_spirit'),
  ('agricole_rum', 'Rhum Agricole', true, 'base_spirit');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('rum', 'white_rum'),
  ('rum', 'dark_rum'),
  ('rum', 'aged_rum'),
  ('rum', 'jamaican_rum'),
  ('rum', 'agricole_rum')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary forms. 'rhum' alone is intentionally
-- not aliased — it's just the French spelling and could mean either
-- agricole (French Caribbean) or generic rum, so it surfaces as
-- underspecified.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('white rum',         'white_rum'),
  ('silver rum',        'white_rum'),
  ('light rum',         'white_rum'),
  ('dark rum',          'dark_rum'),
  ('aged rum',          'aged_rum'),
  ('gold rum',          'aged_rum'),  -- 'gold' is essentially aged with caramel adjustment; closer to aged than dark
  ('jamaican rum',      'jamaican_rum'),
  ('rhum agricole',     'agricole_rum'),
  ('agricole rhum',     'agricole_rum'),
  ('agricole rum',      'agricole_rum'),
  ('agricole',          'agricole_rum')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
