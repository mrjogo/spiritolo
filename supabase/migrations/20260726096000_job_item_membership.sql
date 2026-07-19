-- Explicit runs (Task 4): job_items members are per-run, not append-versioned.
--
-- The old (entity_type, entity_id, stage, code_version) unique key belonged to
-- the version-as-queue-driver world — one latest-only ledger row per entity. In
-- the explicit-run model the worker processes a run's pending MEMBER rows and
-- UPDATES each in place; the same entity can be a member of many runs over time
-- (re-run flagged/failed items in a fresh run), so member rows must NOT be
-- uniqueness-constrained by (entity, stage, code_version).
--
-- Keep the append-versioned uniqueness ONLY for the CLI cold-build ledger rows
-- (job_id IS NULL); run members (job_id NOT NULL) are deduped by the
-- add_run_items RPC. Existing backfilled rows (all job_id NOT NULL) are simply
-- released from the constraint — no data change, no violation.
alter table public.job_items
  drop constraint if exists job_items_entity_type_entity_id_stage_code_version_key;

create unique index if not exists job_items_ledger_key
  on public.job_items (entity_type, entity_id, stage, code_version)
  where job_id is null;
