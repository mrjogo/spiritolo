-- Address Supabase database linter warnings flagged on staging:
--   - 0014 extension_in_public: pg_trgm in `public`
--   - 0028/0029 *_security_definer_function_executable on
--     handle_new_user, is_admin, rls_auto_enable

------------------------------------------------------------------------
-- 1. Move pg_trgm out of the public schema.
------------------------------------------------------------------------
-- The `extensions` schema is part of the standard Supabase setup and is
-- already on the search_path. Indexes that reference gin_trgm_ops bind
-- to the operator class by OID, so the move is transparent to existing
-- indexes (recipes_name_trgm_idx, recipes_ingredients_trgm_idx).

alter extension pg_trgm set schema extensions;

------------------------------------------------------------------------
-- 2. Switch is_admin() from SECURITY DEFINER to SECURITY INVOKER.
------------------------------------------------------------------------
-- The function reads `profiles.is_admin where id = auth.uid()`. Under
-- SECURITY INVOKER:
--   - For an authenticated user: the profiles_self_read RLS policy
--     permits reading their own row, so the function returns the right
--     value without needing elevated privileges.
--   - For anon: the call fails with "permission denied" (anon has no
--     grants on profiles after the lockdown). That is the correct
--     behavior — anon has no business asking who's admin.
-- Eliminates both 0028 and 0029 lints for is_admin.

create or replace function public.is_admin() returns boolean
  language sql security invoker stable
  set search_path = public
  as $$
    select coalesce((select is_admin from profiles where id = auth.uid()), false)
  $$;

------------------------------------------------------------------------
-- 3. Hide handle_new_user() from the REST API surface.
------------------------------------------------------------------------
-- The function MUST stay SECURITY DEFINER — its job is to insert into
-- profiles bypassing the table's (deny-by-default-on-write) RLS, run
-- as the trigger machinery during auth.users INSERT.
-- Postgres trigger execution does NOT consult EXECUTE grants on the
-- trigger function (it only checks grants for CALL/RPC), so revoking
-- EXECUTE from public/anon/authenticated does NOT break the trigger.

revoke execute on function public.handle_new_user() from public;
revoke execute on function public.handle_new_user() from anon;
revoke execute on function public.handle_new_user() from authenticated;

------------------------------------------------------------------------
-- 4. Defensively revoke on rls_auto_enable() if it exists.
------------------------------------------------------------------------
-- This function is auto-installed on some Supabase Cloud projects and
-- does not exist on the local DB or in any of our migrations. Guard
-- with `if exists` so the migration applies cleanly in both contexts.

do $$
begin
  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'rls_auto_enable'
  ) then
    execute 'revoke execute on function public.rls_auto_enable() from public';
    execute 'revoke execute on function public.rls_auto_enable() from anon';
    execute 'revoke execute on function public.rls_auto_enable() from authenticated';
  end if;
end $$;
