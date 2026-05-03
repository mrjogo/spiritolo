-- Address remaining Supabase database linter WARN-level findings:
--   - 0003 auth_rls_initplan on profiles_self_read (auth.uid()
--     re-evaluated per row)
--   - 0006 multiple_permissive_policies on profiles SELECT for
--     authenticated (profiles_self_read + profiles_admin_read)
--   - 0027 pg_graphql_authenticated_table_exposed on every
--     authenticated-readable public table (we don't use GraphQL —
--     the Vite frontend talks REST/PostgREST only)

------------------------------------------------------------------------
-- 1. Drop pg_graphql (we use REST exclusively).
------------------------------------------------------------------------
-- The Vite frontend uses @supabase/supabase-js which talks to PostgREST
-- under /rest/v1/. The /graphql/v1/ endpoint provided by pg_graphql is
-- never called. Dropping the extension shrinks the attack surface and
-- silences the 0027 lint warnings for all authenticated-readable tables
-- (~14 warnings on staging where pg_graphql is auto-installed).
-- Cloud-only: this is a no-op on local dev, where pg_graphql is not
-- installed by default.

drop extension if exists pg_graphql cascade;

------------------------------------------------------------------------
-- 2. Combine profiles_self_read + profiles_admin_read into one policy.
------------------------------------------------------------------------
-- Both policies are permissive (OR'd at evaluation time), and the
-- linter flags this as a per-row perf concern. Combining them into a
-- single policy with the same disjunction expression eliminates the
-- duplicate evaluation. The is_admin() short-circuit also covers the
-- "admin can see anyone's profile" case implicitly.
--
-- Wrap auth.uid() in (select auth.uid()) so Postgres treats it as an
-- initplan (computed once per query) instead of a per-row function
-- call — addresses lint 0003.

drop policy if exists profiles_self_read on profiles;
drop policy if exists profiles_admin_read on profiles;

create policy profiles_read on profiles
  for select to authenticated
  using (id = (select auth.uid()) or is_admin());
