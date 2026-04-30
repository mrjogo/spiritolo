-- Amari.
-- Brand-as-substance applies across the family: each major amaro is its own
-- cluster identity at the expression level because cocktail vocabulary names
-- each as a substance ("a Cynar", "Campari", "Fernet"), not as a generic
-- class. No broader type meaningfully groups them — Campari, Cynar, and
-- Fernet-Branca are radically different flavor profiles even though all are
-- technically amari. The amaro family parent stays non-cluster; recipes
-- specifying generic "amaro" surface as underspecified in the dedup audit.
--
-- Brand nodes float at the top level (no parent); expressions are parented
-- to [brand, amaro]. For eponymous products with no bottle descriptor
-- (Campari, Aperol, Cynar), the expression slug appends the family-parent
-- slug (`_amaro`) to disambiguate from the brand slug. Display name stays
-- the bottle name.
update taxonomy_nodes set role_default = 'modifier' where slug = 'amaro';

-- Brand nodes (top-level, no parent — brands span categories).
insert into taxonomy_nodes (slug, display_name, role) values
  ('campari',     'Campari',         'brand'),  -- Davide Campari-Milano N.V.
  ('aperol',      'Aperol',          'brand'),  -- originally Barbieri (Padua, 1919); now Campari Group
  ('cynar',       'Cynar',           'brand'),  -- originally Pezziol; now Campari Group
  ('branca',      'Branca',          'brand'),  -- Fratelli Branca Distillerie (Milan, 1845)
  ('montenegro',  'Montenegro',      'brand'),  -- Gruppo Montenegro (Bologna, 1885)
  ('nonino',      'Nonino',          'brand'),  -- Nonino Distillatori (Friuli)
  ('averna',      'Averna',          'brand'),  -- originally Fratelli Averna (Sicily, 1868); now Campari Group
  ('meletti',     'Meletti',         'brand'),  -- Meletti (Ascoli Piceno, 1870)
  ('lucano',      'Lucano',          'brand'),  -- Amaro Lucano S.p.A. (Pisticci, Basilicata)
  ('ramazzotti',  'Ramazzotti',      'brand'),  -- originally Ramazzotti (Milan, 1815); now Pernod Ricard
  ('paolucci',    'Paolucci',        'brand'),  -- Paolucci (Sora, Lazio, 1873) — makes Amaro Ciociaro
  ('braulio',     'Braulio',         'brand'),  -- Cantine Peloni (Bormio); now Caffo Group
  ('bosca',       'Bosca',           'brand');  -- Bosca / Tosti (Canelli, Piemonte) — makes Cardamaro

insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  -- Major amari named in the dedup spec.
  ('campari_amaro',    'Campari',                    'expression', true, 'modifier'),
  ('aperol_amaro',     'Aperol',                     'expression', true, 'modifier'),
  ('cynar_amaro',      'Cynar',                      'expression', true, 'modifier'),
  ('fernet_branca',    'Fernet-Branca',              'expression', true, 'modifier'),
  ('amaro_montenegro', 'Amaro Montenegro',           'expression', true, 'modifier'),
  ('amaro_nonino',     'Amaro Nonino Quintessentia', 'expression', true, 'modifier'),
  -- Long tail commonly seen in cocktail recipes.
  ('amaro_averna',     'Amaro Averna',               'expression', true, 'modifier'),
  ('amaro_meletti',    'Amaro Meletti',              'expression', true, 'modifier'),
  ('amaro_lucano',     'Amaro Lucano',               'expression', true, 'modifier'),
  ('amaro_ramazzotti', 'Amaro Ramazzotti',           'expression', true, 'modifier'),
  ('amaro_ciociaro',   'Amaro Ciociaro',             'expression', true, 'modifier'),
  ('amaro_braulio',    'Amaro Braulio',              'expression', true, 'modifier'),
  ('cardamaro',        'Cardamaro Vino Amaro',       'expression', true, 'modifier');

-- Edges: each expression dual-parented to [brand, amaro family].
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('amaro',         'campari_amaro'),
  ('campari',       'campari_amaro'),
  ('amaro',         'aperol_amaro'),
  ('aperol',        'aperol_amaro'),
  ('amaro',         'cynar_amaro'),
  ('cynar',         'cynar_amaro'),
  ('amaro',         'fernet_branca'),
  ('branca',        'fernet_branca'),
  ('amaro',         'amaro_montenegro'),
  ('montenegro',    'amaro_montenegro'),
  ('amaro',         'amaro_nonino'),
  ('nonino',        'amaro_nonino'),
  ('amaro',         'amaro_averna'),
  ('averna',        'amaro_averna'),
  ('amaro',         'amaro_meletti'),
  ('meletti',       'amaro_meletti'),
  ('amaro',         'amaro_lucano'),
  ('lucano',        'amaro_lucano'),
  ('amaro',         'amaro_ramazzotti'),
  ('ramazzotti',    'amaro_ramazzotti'),
  ('amaro',         'amaro_ciociaro'),
  ('paolucci',      'amaro_ciociaro'),
  ('amaro',         'amaro_braulio'),
  ('braulio',       'amaro_braulio'),
  ('amaro',         'cardamaro'),
  ('bosca',         'cardamaro')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug;

-- Aliases: cocktail-vocabulary shortcuts. The eponymous shorthands
-- ('campari', 'aperol', 'cynar', 'fernet') resolve to the expression node
-- (the cluster identity) rather than the brand node, matching cocktail
-- vocabulary intent.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('campari',                    'campari_amaro'),
  ('aperol',                     'aperol_amaro'),
  ('cynar',                      'cynar_amaro'),
  ('fernet',                     'fernet_branca'),
  ('fernet branca',              'fernet_branca'),
  ('montenegro',                 'amaro_montenegro'),
  ('nonino',                     'amaro_nonino'),
  ('amaro nonino',               'amaro_nonino'),
  ('averna',                     'amaro_averna'),
  ('meletti',                    'amaro_meletti'),
  ('lucano',                     'amaro_lucano'),
  ('ramazzotti',                 'amaro_ramazzotti'),
  ('ciociaro',                   'amaro_ciociaro'),
  ('cio ciaro',                  'amaro_ciociaro'),
  ('amaro cio ciaro',            'amaro_ciociaro'),
  ('amaro ciociaro',             'amaro_ciociaro'),
  ('paolucci amaro ciociaro',    'amaro_ciociaro'),
  ('braulio',                    'amaro_braulio'),
  ('cardamaro',                  'cardamaro')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug;
