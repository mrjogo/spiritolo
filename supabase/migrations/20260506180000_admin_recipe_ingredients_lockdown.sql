-- Move recipe_ingredients from RLS tier (a) "eventually anon" to
-- tier (c) "admin only", and extend the column grant so admins can
-- read the parser-output columns the curator UI needs.
--
-- The previous policy (recipe_ingredients_temp_authed_read) admitted
-- any authenticated session. Curator-only access is the intended end
-- state per docs/superpowers/specs/2026-05-06-curator-cross-links-design.md.

drop policy if exists recipe_ingredients_temp_authed_read on recipe_ingredients;
drop policy if exists recipe_ingredients_admin_read       on recipe_ingredients;

create policy recipe_ingredients_admin_read on recipe_ingredients
  for select to authenticated
  using (is_admin());

-- Extend column grant. The earlier (recipe_id, taxonomy_node_id)
-- grant from 20260501120000_create_taxonomy_public.sql is preserved
-- by listing both columns again — repeating an existing GRANT is a
-- no-op in Postgres.
grant select (
  id, recipe_id, position, raw_text,
  amount, amount_max, unit, name, modifier,
  role, parse_status, taxonomy_node_id
) on recipe_ingredients to authenticated;
