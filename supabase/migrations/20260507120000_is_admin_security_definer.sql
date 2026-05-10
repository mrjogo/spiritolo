-- Switch is_admin() back to SECURITY DEFINER to break the
-- profiles-RLS recursion that surfaced once recipe_ingredients
-- started using is_admin() in its RLS policy.
--
-- Background:
--   profiles SELECT policy (20260503190000_more_lint_fixes.sql) is
--   `using (id = (select auth.uid()) or is_admin())`. The OR was
--   intended to short-circuit on the id match — but Postgres does NOT
--   guarantee OR short-circuit evaluation. With recipe_ingredients
--   RLS (20260506180000_admin_recipe_ingredients_lockdown.sql) now
--   calling is_admin() too — especially under PostgREST embed queries
--   that nest the RLS evaluation — the planner evaluates is_admin()
--   even for the user's own profile row. is_admin() reads profiles,
--   which evaluates is_admin() again, and so on until the stack runs
--   out (`ERROR: stack depth limit exceeded`).
--
-- Fix: SECURITY DEFINER bypasses RLS on profiles inside the function,
-- which terminates the chain. The function remains narrowly scoped
-- (read-only, single column, single row keyed on auth.uid()), so the
-- privilege boost cannot be misused. `set search_path = ''` plus the
-- fully-qualified `public.profiles` reference satisfies lint 0028
-- (function_search_path_mutable). Lint 0029 (definer_security) will
-- re-fire as a WARN; we accept it given the narrow function scope and
-- the alternative (recursive RLS that brings down the page) is worse.

create or replace function public.is_admin() returns boolean
  language sql security definer stable
  set search_path = ''
  as $$
    select coalesce(
      (select is_admin from public.profiles where id = auth.uid()),
      false
    )
  $$;
