-- Explicit runs (Task 3): the run-lifecycle + browsing RPC surface.
--
-- The queue-selection UI assembles a run explicitly: create a draft run, load
-- entities into it (by explicit ids or by a JIRA-style filter over the stage's
-- eligible pool), pick an LLM tier, then Start. These SECURITY DEFINER functions
-- are that write/read surface; the committed web hooks in web/src/ui/runs/*.ts
-- call them by the exact argument names used here (create_run(stage,apply_mode),
-- run_items(job_id,p_filter,sort,limit,offset), …).
--
-- Every function follows the house RPC contract: security definer,
-- `set search_path = ''`, a public.is_admin() gate raising 42501, EXECUTE revoked
-- from public and granted to authenticated. Fully schema-qualified references.
--
-- p_filter jsonb shape (shared by eligible_pool and run_items):
--   {"status":["flagged","failed"], "source":["diffordsguide"],
--    "code_version_before":"v4", "search":"neg"}
-- Arrays are OR *within* a key; keys AND *across* each other. An absent key is
-- unconstrained.

-- ---------------------------------------------------------------------------
-- 1. Internal helpers (revoked from public — reached only via the gated RPCs).
-- ---------------------------------------------------------------------------

-- _sort_clause: turn a UI sort token into a safe `alias.col dir` ORDER BY snippet.
-- Accepts both the web form ("title:asc") and bare tokens ("last_run_desc"). The
-- column is whitelisted and the direction constrained to asc/desc, so the result
-- is injection-safe for interpolation into a dynamic ORDER BY.
create or replace function public._sort_clause(
  p_sort text, p_allowed text[], p_default_col text, p_alias text
) returns text
language plpgsql
immutable
set search_path = ''
as $$
declare
  v_col text;
  v_dir text;
  v_order text;
begin
  p_sort := coalesce(p_sort, '');
  v_col := lower(split_part(p_sort, ':', 1));
  v_dir := lower(nullif(split_part(p_sort, ':', 2), ''));
  if v_dir is null then
    if right(v_col, 4) = '_asc' then
      v_dir := 'asc'; v_col := left(v_col, length(v_col) - 4);
    elsif right(v_col, 5) = '_desc' then
      v_dir := 'desc'; v_col := left(v_col, length(v_col) - 5);
    else
      v_dir := 'desc';
    end if;
  end if;
  -- 'status' is the UI's name for a run item's task_state.
  if v_col = 'status' and 'task_state' = any (p_allowed) then
    v_col := 'task_state';
  end if;
  if not (v_col = any (p_allowed)) then
    v_col := p_default_col;
  end if;
  if v_dir not in ('asc', 'desc') then
    v_dir := 'desc';
  end if;
  v_order := format('%I.%I %s', p_alias, v_col, v_dir);
  if v_col = 'last_run' then
    v_order := v_order || case when v_dir = 'asc' then ' nulls first' else ' nulls last' end;
  end if;
  return v_order;
end;
$$;

-- _estimate_cents: rough per-item cost estimate for a stage on a provider. Free
-- (deterministic) work is 0; any hosted LLM tier is a nominal 1 cent/item — the
-- estimate is a confirm-modal hint, not a billing figure.
create or replace function public._estimate_cents(p_stage text, p_provider text)
returns int
language sql
immutable
set search_path = ''
as $$
  select case when p_provider is null then 0 else 1 end;
$$;

-- _eligible_base: the stage's eligible pool, one row per candidate entity with
-- its current stage status + last-run marker, filtered by p_filter. The universe
-- is recipes for every recipe-backed stage and pages for extract. "status" is the
-- most-recent COMPLETED job_item state (applied/flagged/failed/pending_apply), or
-- 'never_run' if none — in-flight members (pending/running) are ignored so a
-- draft membership never masks an entity's last real result.
create or replace function public._eligible_base(p_stage text, p_filter jsonb)
returns table(
  entity_id bigint, title text, source text,
  status text, code_version text, last_run timestamptz
)
language sql
stable
set search_path = ''
as $$
  with universe as (
    select r.id as entity_id,
           coalesce(nullif(btrim(r.title), ''), r.source_url) as title,
           r.site as source
    from public.recipes r
    where p_stage <> 'extract'
    union all
    select p.id, p.url, p.site
    from public.pages p
    where p_stage = 'extract'
  ),
  latest as (
    select distinct on (i.entity_id)
           i.entity_id,
           i.state as status,
           i.code_version,
           coalesce(i.finished_at, i.started_at) as last_run
    from public.job_items i
    where i.stage = p_stage
      and i.state in ('applied', 'flagged', 'failed', 'pending_apply')
    order by i.entity_id, i.id desc
  ),
  joined as (
    select u.entity_id, u.title, u.source,
           coalesce(l.status, 'never_run') as status,
           coalesce(l.code_version, '') as code_version,
           l.last_run
    from universe u
    left join latest l on l.entity_id = u.entity_id
  )
  select entity_id, title, source, status, code_version, last_run
  from joined
  where (p_filter -> 'status' is null
         or status = any (array(select jsonb_array_elements_text(p_filter -> 'status'))))
    and (p_filter -> 'source' is null
         or source = any (array(select jsonb_array_elements_text(p_filter -> 'source'))))
    and (p_filter ->> 'code_version_before' is null
         or code_version < (p_filter ->> 'code_version_before'))
    and (p_filter ->> 'search' is null
         or title ilike '%' || (p_filter ->> 'search') || '%');
$$;

-- _run_items_base: a run's members joined to their entity, with the "why added"
-- reason (stamped at add time) and current task_state, filtered by p_filter. The
-- run_items status filter narrows by task_state (the member's live state).
create or replace function public._run_items_base(p_job_id bigint, p_filter jsonb)
returns table(
  item_id bigint, entity_id bigint, title text, source text,
  why_added text, task_state text, code_version text
)
language sql
stable
set search_path = ''
as $$
  select i.id,
         i.entity_id,
         coalesce(nullif(btrim(r.title), ''), r.source_url, pg.url) as title,
         coalesce(r.site, pg.site) as source,
         coalesce(
           case when i.outcome_payload ->> 'why_added' = 'failed' then 'retry_failed'
                else i.outcome_payload ->> 'why_added' end,
           'never_run'
         ) as why_added,
         i.state as task_state,
         i.code_version
  from public.job_items i
  left join public.recipes r on i.entity_type = 'recipe' and r.id = i.entity_id
  left join public.pages pg on i.entity_type = 'page' and pg.id = i.entity_id
  where i.job_id = p_job_id
    and (p_filter -> 'status' is null
         or i.state = any (array(select jsonb_array_elements_text(p_filter -> 'status'))))
    and (p_filter -> 'source' is null
         or coalesce(r.site, pg.site) = any (array(select jsonb_array_elements_text(p_filter -> 'source'))))
    and (p_filter ->> 'code_version_before' is null
         or i.code_version < (p_filter ->> 'code_version_before'))
    and (p_filter ->> 'search' is null
         or coalesce(nullif(btrim(r.title), ''), r.source_url, pg.url)
            ilike '%' || (p_filter ->> 'search') || '%');
$$;

revoke all on function public._sort_clause(text, text[], text, text) from public;
revoke all on function public._estimate_cents(text, text) from public;
revoke all on function public._eligible_base(text, jsonb) from public;
revoke all on function public._run_items_base(bigint, jsonb) from public;

-- ---------------------------------------------------------------------------
-- 2. Run lifecycle RPCs.
-- ---------------------------------------------------------------------------

-- create_run(stage, apply_mode) -> new draft run id.
create or replace function public.create_run(stage text, apply_mode text default 'auto')
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  insert into public.jobs (stage, kind, state, apply_mode, created_by)
  values (stage, 'run', 'draft'::public.job_state, coalesce(apply_mode, 'auto'), auth.uid())
  returning id into v_id;
  return v_id;
end;
$$;

-- add_run_items(job_id, entity_type, entity_ids) -> number of members added.
-- Idempotent: an entity already a member of this run is skipped. Each new member
-- lands as a 'pending' job_item stamped with why_added (its current pool status).
create or replace function public.add_run_items(
  job_id bigint, entity_type text, entity_ids bigint[]
) returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_stage text;
  v_count int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select stage into v_stage from public.jobs where id = add_run_items.job_id;
  if v_stage is null then
    raise exception 'run % not found', add_run_items.job_id using errcode = '23503';
  end if;

  with latest as (
    select distinct on (i.entity_id) i.entity_id, i.state as status
    from public.job_items i
    where i.stage = v_stage
      and i.state in ('applied', 'flagged', 'failed', 'pending_apply')
    order by i.entity_id, i.id desc
  ),
  ins as (
    insert into public.job_items (
      entity_type, entity_id, stage, code_version, outcome, method, state,
      job_id, outcome_payload
    )
    select add_run_items.entity_type, e.id, v_stage, '', 'pending', 'deterministic',
           'pending', add_run_items.job_id,
           jsonb_build_object('why_added', coalesce(l.status, 'never_run'))
    from unnest(add_run_items.entity_ids) as e(id)
    left join latest l on l.entity_id = e.id
    where not exists (
      select 1 from public.job_items m
      where m.job_id = add_run_items.job_id and m.entity_id = e.id and m.stage = v_stage
    )
    returning 1
  )
  select count(*)::int into v_count from ins;
  return v_count;
end;
$$;

-- add_run_items_by_filter(job_id, p_filter) -> number of members added. Server
-- re-derives the eligible set from the filter (the "Select all N matching" path).
create or replace function public.add_run_items_by_filter(job_id bigint, p_filter jsonb)
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_stage text;
  v_etype text;
  v_count int;
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select stage into v_stage from public.jobs where id = add_run_items_by_filter.job_id;
  if v_stage is null then
    raise exception 'run % not found', add_run_items_by_filter.job_id using errcode = '23503';
  end if;
  v_etype := case when v_stage = 'extract' then 'page' else 'recipe' end;

  with base as (
    select b.entity_id, b.status from public._eligible_base(v_stage, v_filter) b
  ),
  ins as (
    insert into public.job_items (
      entity_type, entity_id, stage, code_version, outcome, method, state,
      job_id, outcome_payload
    )
    select v_etype, base.entity_id, v_stage, '', 'pending', 'deterministic', 'pending',
           add_run_items_by_filter.job_id,
           jsonb_build_object('why_added', base.status)
    from base
    where not exists (
      select 1 from public.job_items m
      where m.job_id = add_run_items_by_filter.job_id
        and m.entity_id = base.entity_id and m.stage = v_stage
    )
    returning 1
  )
  select count(*)::int into v_count from ins;
  return v_count;
end;
$$;

-- remove_run_items(job_id, item_ids) -> number removed. Draft runs only.
create or replace function public.remove_run_items(job_id bigint, item_ids bigint[])
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state public.job_state;
  v_count int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select state into v_state from public.jobs where id = remove_run_items.job_id;
  if v_state is distinct from 'draft'::public.job_state then
    raise exception 'run % is not a draft; cannot remove items', remove_run_items.job_id
      using errcode = '22023';
  end if;
  with del as (
    delete from public.job_items
    where job_items.job_id = remove_run_items.job_id
      and job_items.id = any (remove_run_items.item_ids)
    returning 1
  )
  select count(*)::int into v_count from del;
  return v_count;
end;
$$;

-- set_run_llm(job_id, provider, model) — choose the run's LLM tier (pre-start).
create or replace function public.set_run_llm(job_id bigint, provider text, model text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  update public.jobs
  set llm_provider = set_run_llm.provider, llm_model = set_run_llm.model
  where id = set_run_llm.job_id;
end;
$$;

-- start_run(job_id, max_cost_cents) — draft -> queued. Stamps the cost estimate
-- (pending members x per-item estimate) and clears the approval gate so the
-- worker can claim it.
create or replace function public.start_run(job_id bigint, max_cost_cents int default null)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state public.job_state;
  v_stage text;
  v_provider text;
  v_pending int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select state, stage, llm_provider into v_state, v_stage, v_provider
  from public.jobs where id = start_run.job_id;
  if v_state is null then
    raise exception 'run % not found', start_run.job_id using errcode = '23503';
  end if;
  if v_state <> 'draft'::public.job_state then
    raise exception 'run % is not a draft (state=%)', start_run.job_id, v_state
      using errcode = '22023';
  end if;
  select count(*)::int into v_pending
  from public.job_items
  where job_items.job_id = start_run.job_id and job_items.state = 'pending';

  update public.jobs
  set state               = 'queued'::public.job_state,
      max_cost_cents      = start_run.max_cost_cents,
      cost_estimate_cents = v_pending * public._estimate_cents(v_stage, v_provider),
      requires_approval   = (v_provider is not null),
      approved            = true,
      approved_by         = auth.uid(),
      approved_at         = now()
  where id = start_run.job_id;
end;
$$;

-- apply_run_items(job_id, item_ids) -> number applied. Bulk-accepts a hold run's
-- held results: flips pending_apply -> applied (item_ids null = all eligible).
--
-- Materialization note: every current stage writes its content to the live tables
-- during processing (map -> ingredient_resolutions, parse -> recipe_ingredients,
-- …), so "apply" for those stages is the state flip itself — there is no deferred
-- write to replay. When a future stage genuinely holds its output, its held
-- change would be replayed here per stage; today that is a documented no-op.
create or replace function public.apply_run_items(job_id bigint, item_ids bigint[] default null)
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  with upd as (
    update public.job_items
    set state = 'applied', finished_at = now()
    where job_items.job_id = apply_run_items.job_id
      and job_items.state = 'pending_apply'
      and (apply_run_items.item_ids is null or job_items.id = any (apply_run_items.item_ids))
    returning 1
  )
  select count(*)::int into v_count from upd;
  return v_count;
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. Browsing RPCs — eligible_pool / run_items + their facet siblings.
-- ---------------------------------------------------------------------------
-- The list RPCs stamp a `total_count` window column on every row so the pager
-- knows the full match count without a second round-trip. The facet RPCs return
-- {status:{...}, source:{...}} counts, each dimension computed with its OWN key
-- dropped from the filter (JIRA-style: you can still see other values to add).

create or replace function public.eligible_pool(
  stage text, p_filter jsonb, sort text, "limit" int default 50, "offset" int default 0
) returns table(
  entity_id text, title text, source text, status text,
  status_detail text, last_run_label text, total_count bigint
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_limit int := coalesce("limit", 50);
  v_offset int := coalesce("offset", 0);
  v_order text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  v_order := public._sort_clause(
    sort, array['title', 'source', 'status', 'last_run', 'entity_id'], 'last_run', 'b'
  );
  return query execute
    'select b.entity_id::text, b.title, b.source, b.status, null::text, '
    || 'case when b.last_run is null then null else to_char(b.last_run, ''YYYY-MM-DD'') end, '
    || 'count(*) over () '
    || 'from public._eligible_base($1, $2) b order by ' || v_order || ' limit $3 offset $4'
    using stage, v_filter, v_limit, v_offset;
end;
$$;

create or replace function public.eligible_pool_facets(stage text, p_filter jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_status jsonb;
  v_source jsonb;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select coalesce(jsonb_object_agg(status, c), '{}'::jsonb) into v_status
  from (
    select status, count(*) as c
    from public._eligible_base(stage, v_filter - 'status') group by status
  ) s;
  select coalesce(jsonb_object_agg(source, c), '{}'::jsonb) into v_source
  from (
    select source, count(*) as c
    from public._eligible_base(stage, v_filter - 'source') group by source
  ) s;
  return jsonb_build_object('status', v_status, 'source', v_source);
end;
$$;

create or replace function public.run_items(
  job_id bigint, p_filter jsonb, sort text, "limit" int default 50, "offset" int default 0
) returns table(
  item_id text, entity_id text, title text, source text,
  why_added text, task_state text, total_count bigint
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_limit int := coalesce("limit", 50);
  v_offset int := coalesce("offset", 0);
  v_order text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  v_order := public._sort_clause(
    sort, array['title', 'source', 'task_state', 'entity_id', 'item_id'], 'item_id', 'b'
  );
  return query execute
    'select b.item_id::text, b.entity_id::text, b.title, b.source, b.why_added, b.task_state, '
    || 'count(*) over () '
    || 'from public._run_items_base($1, $2) b order by ' || v_order || ' limit $3 offset $4'
    using run_items.job_id, v_filter, v_limit, v_offset;
end;
$$;

create or replace function public.run_items_facets(job_id bigint, p_filter jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_status jsonb;
  v_source jsonb;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  select coalesce(jsonb_object_agg(task_state, c), '{}'::jsonb) into v_status
  from (
    select task_state, count(*) as c
    from public._run_items_base(run_items_facets.job_id, v_filter - 'status') group by task_state
  ) s;
  select coalesce(jsonb_object_agg(source, c), '{}'::jsonb) into v_source
  from (
    select source, count(*) as c
    from public._run_items_base(run_items_facets.job_id, v_filter - 'source') group by source
  ) s;
  return jsonb_build_object('status', v_status, 'source', v_source);
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. runs — the run-list read view the UI reads directly (not an RPC).
-- ---------------------------------------------------------------------------
-- One row per run with the item roll-ups the runs list + confirm modal need.
-- security_invoker so the jobs/job_items admin-read RLS governs. The composition
-- counts (flagged/never_run/failed) come from each member's why_added stamp, so
-- they read the task set as ASSEMBLED even while every member is still pending.
create or replace view public.runs with (security_invoker = true) as
select
  j.id,
  j.stage,
  case j.state when 'succeeded' then 'done' else j.state::text end as state,
  j.apply_mode,
  j.llm_provider,
  j.llm_model,
  coalesce(c.task_count, 0)     as task_count,
  coalesce(c.flagged_count, 0)  as flagged_count,
  coalesce(c.never_run_count, 0) as never_run_count,
  coalesce(c.failed_count, 0)   as failed_count,
  j.cost_estimate_cents,
  j.max_cost_cents,
  j.created_at,
  j.created_by
from public.jobs j
left join lateral (
  select
    count(*) as task_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'flagged')   as flagged_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'never_run') as never_run_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'failed')    as failed_count
  from public.job_items i
  where i.job_id = j.id
) c on true;

grant select on public.runs to authenticated;

-- ---------------------------------------------------------------------------
-- 5. Grants — the RPCs are the sole write/read path for authenticated admins.
-- ---------------------------------------------------------------------------
revoke all on function public.create_run(text, text) from public;
grant execute on function public.create_run(text, text) to authenticated;

revoke all on function public.add_run_items(bigint, text, bigint[]) from public;
grant execute on function public.add_run_items(bigint, text, bigint[]) to authenticated;

revoke all on function public.add_run_items_by_filter(bigint, jsonb) from public;
grant execute on function public.add_run_items_by_filter(bigint, jsonb) to authenticated;

revoke all on function public.remove_run_items(bigint, bigint[]) from public;
grant execute on function public.remove_run_items(bigint, bigint[]) to authenticated;

revoke all on function public.set_run_llm(bigint, text, text) from public;
grant execute on function public.set_run_llm(bigint, text, text) to authenticated;

revoke all on function public.start_run(bigint, int) from public;
grant execute on function public.start_run(bigint, int) to authenticated;

revoke all on function public.apply_run_items(bigint, bigint[]) from public;
grant execute on function public.apply_run_items(bigint, bigint[]) to authenticated;

revoke all on function public.eligible_pool(text, jsonb, text, int, int) from public;
grant execute on function public.eligible_pool(text, jsonb, text, int, int) to authenticated;

revoke all on function public.eligible_pool_facets(text, jsonb) from public;
grant execute on function public.eligible_pool_facets(text, jsonb) to authenticated;

revoke all on function public.run_items(bigint, jsonb, text, int, int) from public;
grant execute on function public.run_items(bigint, jsonb, text, int, int) to authenticated;

revoke all on function public.run_items_facets(bigint, jsonb) from public;
grant execute on function public.run_items_facets(bigint, jsonb) to authenticated;
