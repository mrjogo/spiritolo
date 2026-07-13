-- stage_queue_counts: real per-stage content-queue depth for the /ops
-- dashboard, replacing the StageCard's content-queue-depth placeholder.
--
-- Mirrors the NOT-EXISTS work-queue predicate every registered stage_fn
-- already runs (ingredients/pipeline/ledger.work_queue and the pages-scoped
-- variant in pipeline/stages/extract.py): a content entity is queued for a
-- stage when it qualifies AND carries no `stage_runs` row for that stage at
-- the stage's current version.
--
-- stage_queue_versions is the one place that names, per stage, which content
-- table it reads and which version string is current. Those version strings
-- are copies of the Python constants (EXTRACTOR_VERSION, PARSER_VERSION,
-- MAPPER_VERSION, CONVERTER_VERSION, DEDUP_VERSION) — there is no live link
-- between the two, so a version bump must update both; a DB test
-- (ingredients/tests/test_stage_queue_counts.py) imports the Python constants
-- and asserts they match this table's seed, so drift fails loudly instead of
-- silently under/over-counting a stage's queue.
--
-- Only stages with an actual Postgres-backed qualifying predicate are seeded
-- here. discover/classify/fetch still run against the scraper's SQLite work
-- queue (see CLAUDE.md), so they have no row; the RPC simply omits them from
-- its result rather than fabricating a count, and the dashboard renders those
-- stages' queue depth as "not tracked" rather than a number.

create table stage_queue_versions (
  stage         text primary key,
  version       text not null,
  content_table text not null check (content_table in ('pages', 'recipes'))
);

insert into stage_queue_versions (stage, version, content_table) values
  ('extract',  'v1',  'pages'),
  ('parse',    'v10', 'recipes'),
  ('map',      'v1',  'recipes'),
  ('convert',  'v1',  'recipes'),
  ('cluster',  'v1',  'recipes'),
  ('export',   'v1',  'recipes');

-- Admin-only read, mirroring stage_config: RLS on, one authenticated +
-- is_admin() policy, explicit grant (anon gets nothing at all).
alter table stage_queue_versions enable row level security;

create policy stage_queue_versions_admin_read on stage_queue_versions
  for select to authenticated
  using (is_admin());

grant select on stage_queue_versions to authenticated;

-- The RPC itself must be SECURITY DEFINER (not a security_invoker view, the
-- pattern stage_run_outcome_counts uses): it reads `pages`, which carries RLS
-- with zero policies and no grant to anon/authenticated at all (deny-all by
-- design — see 20260715090000_pages.sql), so an invoker-rights read would
-- fail outright for every caller, admin included. This mirrors
-- get_taxonomy_node_blockers: an explicit is_admin() check inside a
-- SECURITY DEFINER body, gating a table that otherwise has no client-facing
-- read path.
create or replace function public.stage_queue_counts()
returns table(stage text, queue_depth bigint)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  return query
  select
    v.stage,
    case v.content_table
      when 'pages' then (
        select count(*)
        from public.pages p
        where p.content_type = any(array['drink_recipe'])
          and p.r2_key is not null
          and not exists (
            select 1 from public.stage_runs r
            where r.entity_type = 'page' and r.entity_id = p.id
              and r.stage = v.stage and r.version = v.version
          )
      )
      when 'recipes' then (
        select count(*)
        from public.recipes c
        where not exists (
          select 1 from public.stage_runs r
          where r.entity_type = 'recipe' and r.entity_id = c.id
            and r.stage = v.stage and r.version = v.version
        )
      )
    end as queue_depth
  from public.stage_queue_versions v
  order by v.stage;
end;
$$;

revoke all on function public.stage_queue_counts() from public;
grant execute on function public.stage_queue_counts() to authenticated;
