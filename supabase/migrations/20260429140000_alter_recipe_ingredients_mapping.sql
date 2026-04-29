-- Mapping output: which canonical node this ingredient resolved to,
-- which cascade layer (or phase) decided, and the version under which.
alter table recipe_ingredients
  add column taxonomy_node_id bigint references taxonomy_nodes(id),
  add column mapper_source    text check (mapper_source in
    ('alias', 'lexical', 'pending_llm', 'llm', 'abstain')),
  add column mapper_version   text,
  add column mapper_at        timestamptz;

create index recipe_ingredients_taxonomy_idx
  on recipe_ingredients (taxonomy_node_id)
  where taxonomy_node_id is not null;

create index recipe_ingredients_pending_llm_idx
  on recipe_ingredients (mapper_version)
  where mapper_source = 'pending_llm';
