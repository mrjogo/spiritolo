-- Keep-alive RPC for the Supabase free-tier pause timer.
--
-- The whole data schema is locked down to `authenticated` (see
-- 20260502140000_auth_and_rls_lockdown.sql), so anon has no readable surface
-- to ping. This adds one deliberately trivial, anon-callable function whose
-- only job is to execute a query in Postgres — enough DB activity to reset the
-- 7-day auto-pause timer — while exposing zero data.
--
-- Called by .github/workflows/keepalive.yml via POST /rest/v1/rpc/keepalive
-- using the publishable (anon) key. Returns the constant 1.

create or replace function public.keepalive()
  returns int
  language sql
  security definer
  set search_path = public
  as 'select 1';

-- Lock down, then expose only EXECUTE to anon (the publishable key's role).
revoke all on function public.keepalive() from public;
grant execute on function public.keepalive() to anon;
