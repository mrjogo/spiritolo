-- Extend the authenticated column grant on recipe_ingredients to
-- include flag_reason. The lockdown migration
-- (20260506180000_admin_recipe_ingredients_lockdown.sql) restricts
-- authenticated reads to a column allow-list; flag_reason was added
-- in 20260521120000_proposal_review_schema.sql but not added to that
-- list. Without this grant, the React Query useFlagReasons hook fails
-- with `permission denied for column flag_reason` even for admins.
--
-- Repeating the prior column grant is a no-op in Postgres (additive).

grant select (
  id, recipe_id, position, raw_text,
  amount, amount_max, unit, name, modifier,
  role, parse_status, taxonomy_node_id, flag_reason
) on public.recipe_ingredients to authenticated;
