-- Run cockpit backend: everything the /ops run-detail page needs to answer
-- "is this run healthy?" and "what do I do next?" —
--   1. the `runs` view gains the live/terminal fields (actual cost, error
--      detail, worker attribution + heartbeat, timing, and per-item-state
--      progress counts);
--   2. `worker_status` records worker liveness + which providers each worker
--      can service (global health signal + Start pre-flight);
--   3. `retry_run` re-drives a finished run's residue.

-- ---------------------------------------------------------------------------
-- 1. Expand the `runs` read view. create-or-replace only allows appending
--    columns, so the original 13 stay in place and order; the cockpit fields
--    are added at the end. The lateral roll-up gains per-current-state counts
--    (progress) alongside the existing why_added composition counts.
-- ---------------------------------------------------------------------------
create or replace view public.runs with (security_invoker = true) as
select
  j.id,
  j.stage,
  case j.state when 'succeeded' then 'done' else j.state::text end as state,
  j.llm_provider,
  j.llm_model,
  coalesce(c.task_count, 0)      as task_count,
  coalesce(c.flagged_count, 0)   as flagged_count,
  coalesce(c.never_run_count, 0) as never_run_count,
  coalesce(c.failed_count, 0)    as failed_count,
  j.cost_estimate_cents,
  j.max_cost_cents,
  j.created_at,
  j.created_by,
  -- cockpit fields (appended) --------------------------------------------
  j.cost_actual_cents,
  j.error_code,
  j.error_detail,
  j.worker_id,
  j.last_heartbeat,
  j.started_at,
  j.finished_at,
  coalesce(c.items_pending, 0) as items_pending,
  coalesce(c.items_applied, 0) as items_applied,
  coalesce(c.items_flagged, 0) as items_flagged,
  coalesce(c.items_failed, 0)  as items_failed
from public.jobs j
left join lateral (
  select
    count(*)                                                                as task_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'flagged')   as flagged_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'never_run')  as never_run_count,
    count(*) filter (where i.outcome_payload ->> 'why_added' = 'failed')     as failed_count,
    count(*) filter (where i.state = 'pending') as items_pending,
    count(*) filter (where i.state = 'applied') as items_applied,
    count(*) filter (where i.state = 'flagged') as items_flagged,
    count(*) filter (where i.state = 'failed')  as items_failed
  from public.job_items i
  where i.job_id = j.id
) c on true;

grant select on public.runs to authenticated;

-- ---------------------------------------------------------------------------
-- 2. worker_status: one row per worker, refreshed each loop pass. `last_seen`
--    is the liveness signal (a queued run with no fresh worker is the #7
--    black hole); `providers` is what the worker can actually service, so the
--    Start modal can warn before assembling a run for a provider the worker
--    has no key for. The worker writes over the direct postgres connection
--    (bypasses RLS); /ops reads it (admin-only).
-- ---------------------------------------------------------------------------
create table if not exists public.worker_status (
  worker_id text primary key,
  last_seen timestamptz not null default now(),
  providers text[] not null default '{}',
  stages    text[] not null default '{}'
);

alter table public.worker_status enable row level security;

drop policy if exists worker_status_admin_read on public.worker_status;
create policy worker_status_admin_read on public.worker_status
  for select using (public.is_admin());

grant select on public.worker_status to authenticated;

-- ---------------------------------------------------------------------------
-- 3. retry_run(job_id): re-drive a finished run's residue. Failed items go back
--    to pending (unprocessed items already are); applied/flagged are left as-is.
--    The job is re-queued with its error/timing cleared, so the worker re-claims
--    it and processes exactly the residue.
-- ---------------------------------------------------------------------------
create or replace function public.retry_run(job_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state public.job_state;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  select state into v_state from public.jobs where id = retry_run.job_id for update;
  if v_state is null then
    raise exception 'run % not found', retry_run.job_id using errcode = '23503';
  end if;
  if v_state not in ('failed', 'cancelled', 'done') then
    raise exception 'run % is not finished (state=%)', retry_run.job_id, v_state
      using errcode = '22023';
  end if;

  update public.job_items
  set state = 'pending'
  where job_items.job_id = retry_run.job_id and job_items.state = 'failed';

  update public.jobs
  set state             = 'queued'::public.job_state,
      error_code        = null,
      error_detail      = null,
      cost_actual_cents = null,
      started_at        = null,
      finished_at       = null,
      worker_id         = null
  where id = retry_run.job_id;
end;
$$;

revoke all on function public.retry_run(bigint) from public;
grant execute on function public.retry_run(bigint) to authenticated;
