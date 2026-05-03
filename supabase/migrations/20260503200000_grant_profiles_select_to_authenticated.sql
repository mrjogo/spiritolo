-- Grant SELECT on profiles to authenticated.
--
-- The auth_and_rls_lockdown migration created `profiles` and added an
-- RLS policy `for select to authenticated`, but never explicitly
-- granted SELECT on the table. On the local Supabase emulator this is
-- a no-op because the public schema's default privileges auto-grant
-- new tables to `authenticated` — so logging in worked locally. On
-- Supabase Cloud (staging) the default privileges don't grant on
-- migration-created tables, so PostgREST returned 403/42501
-- ("permission denied for table profiles") for AuthProvider's
-- `select is_admin from profiles` query, blocking sign-in completely.
--
-- RLS still gates row visibility via the profiles_read policy
-- (`id = auth.uid() or is_admin()`), so this grant only enables the
-- table-level access PostgREST needs before it consults the policy.

grant select on public.profiles to authenticated;
