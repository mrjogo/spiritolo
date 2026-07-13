-- Read surfaces the /ops DB browsers need, beyond what already exists:
--
--   1. recipe_exports carries RLS with zero policies and no grant (the
--      "admin/service only" note in 20260720120000_content_relational_model.sql
--      never actually wired the admin half up). Add the same
--      authenticated + is_admin() policy + grant that stage_runs and
--      stage_config already use, so the exports browser can read frozen
--      bundles directly.
--   2. audit.log lives outside the `public`/`graphql_public` schemas
--      PostgREST exposes (see supabase/config.toml), so no client role can
--      reach it at all today, admin or not. audit_log_public is a plain
--      security_invoker projection in `public` — the same pattern as
--      recipes_public/taxonomy_public/stage_run_outcome_counts — so the
--      existing audit_log_admin_read RLS policy on audit.log (already
--      is_admin()-gated) is what actually decides who sees a row; the view
--      adds no privilege of its own.

alter table recipe_exports enable row level security;

create policy recipe_exports_admin_read on recipe_exports
  for select to authenticated
  using (is_admin());

grant select on recipe_exports to authenticated;

create view public.audit_log_public
  with (security_invoker = true)
as
  select id, ts, table_name, pk, op, actor_kind, actor_id, source,
         before, after, changed_keys
  from audit.log;

grant select on public.audit_log_public to authenticated;
