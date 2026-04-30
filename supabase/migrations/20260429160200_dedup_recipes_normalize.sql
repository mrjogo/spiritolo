-- E's name-normalization output written directly onto recipes.
-- Mirrors D's pattern of writing resolution + source + version directly
-- onto the source table (recipe_ingredients for D). No separate cache.
--
-- Phase 1 (alias + lexical) writes 'alias' or 'lexical' or 'pending_llm'.
-- Phase 2 (LLM) flips 'pending_llm' to 'llm' or 'abstain'.

alter table recipes
  add column canonical_name        text,
  add column canonical_name_source text check (canonical_name_source in
                                     ('alias', 'lexical', 'pending_llm',
                                      'llm', 'abstain')),
  add column normalizer_version    text,
  add column normalized_at         timestamptz;

create index recipes_pending_normalize_idx
  on recipes (canonical_name_source) where canonical_name_source = 'pending_llm';

create index recipes_canonical_name_idx
  on recipes (canonical_name) where canonical_name is not null;
