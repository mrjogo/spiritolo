-- Postgres-as-queue (WS-B22), part 1 of 3: job_batches.
--
-- The OpenAI async-Batch accelerator's bookkeeping row. Created BEFORE jobs
-- because jobs.batch_id FKs it. A batch groups the per-item requests of one
-- metered stage run submitted to a hosted provider's Batch API (50% off, ~24h
-- SLA); the worker reconciles open batches on boot (B24) and ingests results
-- back through the normal stage_run UPSERT path.
--
-- custom_id_map maps the provider's opaque per-line custom_id back to the
-- Spiritolo entity id the result belongs to, so an out-of-order batch response
-- unpacks to the right rows.

create table job_batches (
  id                bigserial primary key,
  provider          text not null default 'openai',
  provider_batch_id text unique,
  state             text not null default 'submitted'
                      check (state in
                        ('submitted', 'in_progress', 'completed', 'failed', 'ingested')),
  custom_id_map     jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- The set the boot reconciler scans: batches still in flight at a provider.
create index job_batches_open_idx on job_batches (id)
  where state in ('submitted', 'in_progress');

-- Deny-all RLS: managed only by the worker/pipeline (function owner) — no
-- policy, so no direct client access. Mirrors the recipegf_* / jobs tables.
alter table job_batches enable row level security;
