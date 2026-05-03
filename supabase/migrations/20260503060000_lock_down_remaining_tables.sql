-- Lock down remaining tables that the initial auth_and_rls_lockdown
-- migration missed. Discovered by an end-of-branch RLS audit:
-- cocktail_aliases was leaking 227 rows to anon (RLS off, anon grant);
-- recipe_clusters and recipe_variants would leak once cluster compute
-- runs; profiles, taxonomy_proposals, taxonomy_provenance had RLS-gated
-- access but stale anon grants from their original create migrations.
--
-- Tier convention (same as the parent lockdown migration):
--   *_temp_authed_read  — tier (a): authenticated only for now,
--                         eventually opens to anon. Find with `grep`.
--   *_admin_read        — tier (c): admin only.

------------------------------------------------------------------------
-- 1. Enable RLS on the two tables that didn't have it.
------------------------------------------------------------------------

alter table cocktail_aliases enable row level security;
alter table recipe_clusters  enable row level security;

------------------------------------------------------------------------
-- 2. Make recipe_variants view security_invoker so it honors the
--    underlying recipes RLS rather than running as its owner.
------------------------------------------------------------------------

alter view recipe_variants set (security_invoker = true);

------------------------------------------------------------------------
-- 3. Revoke all anon access on every still-leaking object.
------------------------------------------------------------------------

revoke all on cocktail_aliases    from anon;
revoke all on recipe_clusters     from anon;
revoke all on recipe_variants     from anon;
revoke all on profiles            from anon;
revoke all on taxonomy_proposals  from anon;
revoke all on taxonomy_provenance from anon;

------------------------------------------------------------------------
-- 4. Tier (a) — temp-auth-gated, eventually anon.
------------------------------------------------------------------------

grant select on cocktail_aliases to authenticated;
create policy cocktail_aliases_temp_authed_read on cocktail_aliases
  for select to authenticated
  using (true);

grant select on recipe_clusters to authenticated;
create policy recipe_clusters_temp_authed_read on recipe_clusters
  for select to authenticated
  using (true);

-- recipe_variants is a view; no policy needed. Authenticated already
-- has select via the original dedup_clusters migration; security_invoker
-- delegates to recipes' temp_authed_read policy for actual row access.

------------------------------------------------------------------------
-- 5. Tier (c) — admin only.
------------------------------------------------------------------------

create policy taxonomy_proposals_admin_read on taxonomy_proposals
  for select to authenticated
  using (is_admin());

create policy taxonomy_provenance_admin_read on taxonomy_provenance
  for select to authenticated
  using (is_admin());
