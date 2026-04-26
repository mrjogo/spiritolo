-- Enable trigram matching for substring/fuzzy ILIKE queries on recipes.
create extension if not exists pg_trgm;

-- Functional GIN index over recipe name. Supports ILIKE '%foo%' on `name`.
create index recipes_name_trgm_idx
  on recipes using gin (name gin_trgm_ops);

-- Functional GIN index over the JSON-encoded recipeIngredient array text.
-- The bracket/quote noise in the JSON encoding is irrelevant to substring match.
create index recipes_ingredients_trgm_idx
  on recipes using gin ((jsonld->>'recipeIngredient') gin_trgm_ops);
