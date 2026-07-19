-- Explicit runs (1/2): extend the job_state enum.
--
-- Adds the two new run states the explicit-runs redesign needs:
--   * 'draft' — a run being assembled (tasks added/removed, LLM tier chosen)
--     before Start; the new default for a freshly-created run.
--   * 'done'  — a finished run (the app maps the legacy 'succeeded' to "done"
--     for display; 'awaiting_approval' stays in the enum but is unused — the
--     Start confirmation modal is the only cost gate now).
--
-- This is deliberately a SEPARATE migration from 20260726090000_explicit_runs.sql
-- because Postgres forbids USING a freshly-added enum value in the same
-- transaction that added it ("unsafe use of new value"). The test conftest and
-- the Supabase CLI both apply each migration file in its own transaction, so
-- splitting the ADD VALUE out lets the next migration set the 'draft' default
-- and insert 'done' backfill jobs freely.

alter type job_state add value if not exists 'draft';
alter type job_state add value if not exists 'done';
