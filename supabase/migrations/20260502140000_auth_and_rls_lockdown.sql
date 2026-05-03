-- Auth + RLS lockdown.
-- See docs/superpowers/specs/2026-05-02-staging-deploy-and-auth-design.md.
--
-- Tier convention (encoded in policy names):
--   *_temp_authed_read  — tier (a): authenticated only for now,
--                         eventually opens to anon. Find with `grep`.
--   *_authed_read       — tier (b): permanently authenticated, no admin gate.
--   *_admin_read        — tier (c): admin only.

------------------------------------------------------------------------
-- 1. profiles + is_admin helper + auto-create trigger
------------------------------------------------------------------------

create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  is_admin boolean not null default false,
  created_at timestamptz not null default now()
);

alter table profiles enable row level security;

create or replace function public.is_admin() returns boolean
  language sql security definer stable
  set search_path = public
  as $$
    select coalesce((select is_admin from profiles where id = auth.uid()), false)
  $$;

create policy profiles_self_read on profiles
  for select to authenticated
  using (id = auth.uid());

create policy profiles_admin_read on profiles
  for select to authenticated
  using (is_admin());

create or replace function public.handle_new_user() returns trigger
  language plpgsql security definer
  set search_path = public
  as $$
  begin
    insert into profiles (id) values (new.id);
    return new;
  end
  $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Backfill profile rows for any users that already existed when this migration
-- was applied. The trigger above only fires for future inserts.
insert into profiles (id)
  select id from auth.users
  on conflict (id) do nothing;

------------------------------------------------------------------------
-- 2. Revoke all anon access to existing data tables and views
------------------------------------------------------------------------

revoke all on recipes              from anon;
revoke all on recipes_public       from anon;
revoke all on recipe_ingredients   from anon;
revoke all on taxonomy_nodes       from anon;
revoke all on taxonomy_edges       from anon;
revoke all on taxonomy_aliases     from anon;
revoke all on taxonomy_public      from anon;

------------------------------------------------------------------------
-- 3. Drop existing public-read policies; recreate under tier convention
------------------------------------------------------------------------

-- tier (a): recipes (eventually anon)
drop policy if exists recipes_public_read on recipes;
create policy recipes_temp_authed_read on recipes
  for select to authenticated
  using (true);

-- tier (a): recipe_ingredients (eventually anon)
drop policy if exists recipe_ingredients_taxonomy_count_read on recipe_ingredients;
create policy recipe_ingredients_temp_authed_read on recipe_ingredients
  for select to authenticated
  using (true);

-- tier (c): taxonomy_nodes (admin only)
drop policy if exists taxonomy_nodes_public_read on taxonomy_nodes;
create policy taxonomy_nodes_admin_read on taxonomy_nodes
  for select to authenticated
  using (is_admin());

-- tier (c): taxonomy_edges (admin only)
drop policy if exists taxonomy_edges_public_read on taxonomy_edges;
create policy taxonomy_edges_admin_read on taxonomy_edges
  for select to authenticated
  using (is_admin());

-- tier (c): taxonomy_aliases (admin only)
drop policy if exists taxonomy_aliases_public_read on taxonomy_aliases;
create policy taxonomy_aliases_admin_read on taxonomy_aliases
  for select to authenticated
  using (is_admin());
