-- Park LLM-batch failures: add 'pending_llm_tried' to mapper_source and
-- canonical_name_source so the chunked Phase-2 drain stops re-submitting
-- names that consistently fail. Operator runs `map retry-failures` /
-- `normalize-names retry-failures` to unpark.

alter table recipe_ingredients
  drop constraint recipe_ingredients_mapper_source_check;

alter table recipe_ingredients
  add constraint recipe_ingredients_mapper_source_check
  check (mapper_source in
    ('alias', 'lexical', 'pending_llm', 'pending_llm_tried',
     'llm', 'abstain'));

alter table recipes
  drop constraint recipes_canonical_name_source_check;

alter table recipes
  add constraint recipes_canonical_name_source_check
  check (canonical_name_source in
    ('alias', 'lexical', 'pending_llm', 'pending_llm_tried',
     'llm', 'abstain'));
