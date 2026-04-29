-- E's three taxonomy_nodes annotations. is_cluster_node marks the antichain
-- used for cluster-key rollup; role_default seeds role classification at
-- substance level; is_defining_garnish flags garnishes that change drink
-- identity (cocktail onion → Gibson, salt rim → Salty Dog, etc.).
--
-- All three default to "off"/null so existing nodes (and any auto-created
-- by D's mapper) are not retroactively promoted into the antichain. Curator
-- review owns every is_cluster_node = true and is_defining_garnish = true.

alter table taxonomy_nodes
  add column is_cluster_node     boolean not null default false,
  add column role_default        text,
  add column is_defining_garnish boolean not null default false;
