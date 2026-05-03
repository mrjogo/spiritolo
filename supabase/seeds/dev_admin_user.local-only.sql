-- ============================================================
-- LOCAL DEV ONLY. DO NOT EVER LOAD ON STAGING OR PRODUCTION.
-- ============================================================
-- Pre-creates a magic-link-ready admin user (admin@local.test) and
-- flips profiles.is_admin so a fresh `supabase db reset` lands you
-- in an admin-ready state without manual Studio steps.
--
-- Sign-in flow (still magic-link, identical to staging):
--   1. /login → enter `admin@local.test` → "Send magic link"
--   2. Open Inbucket at http://127.0.0.1:54324
--   3. Click the link → land in /recipes as admin
--
-- Safety:
--   - File is wired into supabase/config.toml's db.seed.sql_paths so
--     it runs on `supabase db reset` (local) only. The staging
--     bootstrap (spec §6) uses explicit `psql -f` calls and does not
--     reference this file.
--   - The DO block below short-circuits if it detects any real user
--     accounts (any auth.users row whose email isn't in *.local.test
--     or *.local.dev). That's the second-line defense if someone
--     ever runs `supabase db reset` against staging by accident.
--   - Remove this seed (and its entry in config.toml) before doing
--     anything that uploads ALL data to staging via db reset.

do $$
declare
  admin_id  uuid := '00000000-0000-0000-0000-0000000000a1';
  admin_email text := 'admin@local.test';
begin
  -- Bail out if any real-looking users already exist in this DB.
  if exists (
    select 1 from auth.users
    where email !~ '@(local\.test|local\.dev)$'
  ) then
    raise notice 'dev_admin_user.local-only.sql: real users present, skipping';
    return;
  end if;

  insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, created_at, updated_at,
    raw_app_meta_data, raw_user_meta_data
  ) values (
    '00000000-0000-0000-0000-000000000000',
    admin_id,
    'authenticated', 'authenticated',
    admin_email,
    crypt('localdev-admin-password-not-used-for-magic-link', gen_salt('bf')),
    now(), now(), now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb
  )
  on conflict (id) do nothing;

  -- A row in auth.users alone is not enough — GoTrue fails with
  -- "Database error finding user" if there's no matching auth.identities
  -- row. For email-provider users, provider_id is the user's UUID as
  -- text, and identity_data carries sub/email/email_verified.
  insert into auth.identities (
    id, user_id, provider_id, provider, identity_data,
    last_sign_in_at, created_at, updated_at
  ) values (
    gen_random_uuid(),
    admin_id,
    admin_id::text,
    'email',
    jsonb_build_object(
      'sub', admin_id::text,
      'email', admin_email,
      'email_verified', true,
      'phone_verified', false
    ),
    now(), now(), now()
  )
  on conflict (provider_id, provider) do nothing;

  -- The on_auth_user_created trigger inserts the profiles row with
  -- is_admin=false. Flip the flag. The upsert covers re-runs after
  -- something deleted the profiles row but not the auth.users row.
  insert into profiles (id, is_admin) values (admin_id, true)
    on conflict (id) do update set is_admin = true;

  raise notice 'dev_admin_user.local-only.sql: % is admin', admin_email;
end $$;
