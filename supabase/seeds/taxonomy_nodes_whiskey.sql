-- Whiskey subtypes — all major regional/regulatory categories are
-- cluster nodes per the dedup spec.
--
-- Regulatory definitions verified via 27 CFR § 5.143 (US TTB) and the
-- respective regional bodies:
--   * bourbon: ≥51% corn mash, new charred oak barrels, ≤80% ABV
--     distillation, ≤62.5% ABV barrel entry, no additives, USA only.
--   * rye_whiskey: ≥51% rye mash, new charred oak (USA standard).
--   * scotch_whisky: distilled and matured in Scotland for ≥3 years
--     in oak; ≥40% ABV bottling; only water and plain caramel coloring
--     (E150a) permitted as additives.
--   * irish_whiskey: distilled and aged in Ireland for ≥3 years in
--     wooden casks; no added flavors or colorings.
--   * japanese_whisky: per the Japan Spirits & Liqueurs Makers
--     Association rules formalized in 2021 — fermented, distilled,
--     and aged in Japan for ≥3 years; prohibits blending with foreign
--     whisky or non-whisky spirits.
--   * tennessee_whiskey: meets all bourbon requirements PLUS the
--     Lincoln County Process (filtering through or steeping in maple
--     charcoal before barreling); mandated by 2013 Tennessee state
--     law. Clusters separately from bourbon because cocktail recipes
--     calling for "Tennessee whiskey" specifically (Lynchburg
--     Lemonade) differ from generic bourbon recipes.
--
-- Skipped: canadian_whisky (less common in classic cocktails — most
-- "rye whiskey" cocktails today use American rye, though historical
-- recipes sometimes meant Canadian); single_malt_scotch and other
-- scotch sub-styles (single malt is a process category, not a cluster
-- identity in cocktail vocab — recipes calling for "scotch" treat
-- single malt vs blended as variant-level brand call).

insert into taxonomy_nodes (slug, display_name, is_cluster_node, default_role) values
  ('bourbon',           'Bourbon',           true, 'base_spirit'),
  ('rye_whiskey',       'Rye Whiskey',       true, 'base_spirit'),
  ('scotch_whisky',     'Scotch Whisky',     true, 'base_spirit'),
  ('irish_whiskey',     'Irish Whiskey',     true, 'base_spirit'),
  ('japanese_whisky',   'Japanese Whisky',   true, 'base_spirit'),
  ('tennessee_whiskey', 'Tennessee Whiskey', true, 'base_spirit');

insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('whiskey', 'bourbon'),
  ('whiskey', 'rye_whiskey'),
  ('whiskey', 'scotch_whisky'),
  ('whiskey', 'irish_whiskey'),
  ('whiskey', 'japanese_whisky'),
  ('whiskey', 'tennessee_whiskey')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('rye',                 'rye_whiskey'),
  ('rye whiskey',         'rye_whiskey'),
  ('scotch',              'scotch_whisky'),
  ('scotch whiskey',      'scotch_whisky'),
  ('bourbon whiskey',     'bourbon'),
  ('tennessee',           'tennessee_whiskey'),
  ('tennessee whisky',    'tennessee_whiskey'),  -- some bottles spell without the 'e'
  ('irish whiskey',       'irish_whiskey'),
  ('irish whisky',        'irish_whiskey'),
  ('japanese whisky',     'japanese_whisky'),
  ('japanese whiskey',    'japanese_whisky')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
