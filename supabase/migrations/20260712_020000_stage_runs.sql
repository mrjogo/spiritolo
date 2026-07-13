-- B4 — stage_runs: the unified run-ledger for the v2.1 redesign.
--
-- One polymorphic latest-only ledger for ALL stages (Zone-1 + Zone-2 merged),
-- generalizing the per-stage *_runs tables (classify_url_runs, validate_html_
-- runs, classify_drink_runs, extract_runs, recipe_ingredients-as-runs, …) into a
-- single table. Exactly one row per (entity, stage): a re-run UPSERTs.
--
-- Polymorphic by design: (entity_type, entity_id) with NO per-entity FK — a run
-- row can reference a page or a recipe (the content entity) without a hard
-- reference, so the ledger stays a pure cache of derived state that TRUNCATE +
-- re-run reproduces. This also lets the ledger land ahead of the content tables:
-- the greenfield content-pipeline rebuild introduces the real `recipes` /
-- `recipe_ingredients` / `recipe_steps` schema, and this ledger already speaks
-- its entity_type without depending on those tables existing yet.
-- batch_id / job_id are plain bigint columns here (no FK): the jobs / job_batches
-- queue tables are a separate workstream; wiring the FKs is deferred to when
-- those tables land.

create table stage_runs (
  id          bigserial primary key,
  entity_type text   not null check (entity_type in ('page','recipe')),
  entity_id   bigint not null,
  stage       text   not null,   -- discover|classify|fetch|extract|parse|map|role|cluster|export
  version     text   not null,   -- the stage's version constant at run time

  outcome     text not null check (outcome in
                ('resolved','abstain','pending','failed','proposes_new')),
  method      text not null check (method in ('deterministic','llm','manual')),
  confidence  real,
  model_id    text,              -- e.g. 'qwen3:14b', 'gpt-5-mini'; null for deterministic
  cost_cents  numeric,           -- metered spend attributable to this run
  error_code  text,
  batch_id    bigint,            -- FK deferred until job_batches exists
  job_id      bigint,            -- FK deferred until jobs exists
  payload     jsonb,             -- stage-specific detail (raw response, snapshot, breakdown)

  started_at  timestamptz not null default now(),
  finished_at timestamptz,

  unique (entity_type, entity_id, stage)   -- latest-only; re-run UPSERTs
);

-- Work-queue predicate index: "docs at stage S not yet run at version V".
create index stage_runs_queue_idx on stage_runs (stage, version, entity_type);
create index stage_runs_job_idx   on stage_runs (job_id) where job_id is not null;

-- Admin/pipeline read only. RLS on; no anon/authenticated grant. The pipeline
-- writes as the table owner / service_role (BYPASSRLS). Admin UI reads via the
-- authenticated-is_admin policy; anon gets nothing (no grant => permission
-- denied, independent of RLS).
alter table stage_runs enable row level security;

create policy stage_runs_admin_read on stage_runs
  for select to authenticated
  using (is_admin());
