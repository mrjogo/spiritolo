-- Postgres-as-queue: the jobs table.
--
-- A jobs row is dispatch intent: "run <stage> over <payload scope>." The worker
-- claims the oldest runnable job with FOR UPDATE SKIP LOCKED (see queue/claim.py),
-- heartbeats while running, and a reaper requeues jobs whose heartbeat goes
-- stale (see queue/reaper.py) — that requeue is the entire retry story (no
-- broker, no scheduler, no DLQ). Durable history lives in audit_log, not here.
--
-- Free stages (deterministic/local) enqueue straight to 'queued'. Metered
-- stages (hosted LLM, ScraperAPI) enqueue to 'awaiting_approval' with a
-- cost_estimate_cents and are only claimable once an admin approves them —
-- confirm-before-cost. A per-worker max_cost budget is enforced at claim time.

create type job_state as enum (
  'queued',
  'awaiting_approval',
  'claimed',
  'running',
  'succeeded',
  'failed'
);

create table jobs (
  id                  bigserial primary key,
  stage               text not null,
  version             text,
  kind                text not null default 'run'
                        check (kind in ('run', 'reset', 'reconcile')),
  payload             jsonb not null default '{}'::jsonb,
  state               job_state not null default 'queued',
  requires_approval   boolean not null default false,
  approved            boolean not null default false,
  approved_by         uuid references auth.users(id),
  approved_at         timestamptz,
  cost_estimate_cents integer,
  cost_actual_cents   integer,
  max_cost_cents      integer,
  progress            jsonb not null default '{}'::jsonb,
  error_code          text,
  batch_id            bigint references job_batches(id),
  worker_id           text,
  last_heartbeat      timestamptz,
  created_by          uuid references auth.users(id),
  created_at          timestamptz not null default now(),
  started_at          timestamptz,
  finished_at         timestamptz
);

-- Claimable = queued AND (free OR approved). Partial index over created_at so
-- the FIFO claim (`order by created_at ... for update skip locked limit 1`) is
-- index-driven and only ever scans runnable rows.
create index jobs_claimable_idx on jobs (created_at)
  where state = 'queued' and (not requires_approval or approved);

create index jobs_batch_idx on jobs (batch_id);

-- RLS: deny-all writes, admin read only. The SECURITY DEFINER RPCs
-- (enqueue_job / approve_job) are the sole write path; anon has no table grant
-- at all (cannot even select).
alter table jobs enable row level security;

create policy jobs_admin_read on jobs
  for select to authenticated
  using (public.is_admin());

grant select on jobs to authenticated;

-- Realtime: the /ops UI subscribes to live job-status changes (useRealtimeJobs).
-- On a real Supabase cluster the supabase_realtime publication already
-- exists; on a bare Postgres (CI test DB) it doesn't — create it if absent, and
-- add jobs idempotently so re-applying the migration is a no-op.
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'jobs'
  ) then
    alter publication supabase_realtime add table public.jobs;
  end if;
end $$;
