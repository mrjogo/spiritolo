-- "role" was overloaded on taxonomy_nodes: the column meant data-model node
-- kind ('brand'/'expression'/NULL), and its sibling role_default meant the
-- ingredient role this substance defaults to in a recipe. Same word, two
-- concepts on the same row, with a third meaning ("recipe ingredient role")
-- living on recipe_ingredients.role. Rename to disambiguate:
--
--   taxonomy_nodes.role         -> node_kind     (structural)
--   taxonomy_nodes.role_default -> default_role  (ingredient-role default)
--
-- recipe_ingredients.role and .role_source are kept — they are genuinely
-- ingredient roles in a drink.

alter table taxonomy_nodes rename column role         to node_kind;
alter table taxonomy_nodes rename column role_default to default_role;
