-- 20260804100100_job_item_tokens.sql
-- Persist per-call LLM token usage per job_item, rolled up to the parent job on
-- finalize. Populates run-duration telemetry (the estimate_run_seconds history
-- is timing-based; these token columns are the companion cost/throughput signal).
-- Idempotent; all four columns nullable (deterministic items carry no tokens).
alter table public.job_items add column if not exists prompt_tokens int;
alter table public.job_items add column if not exists completion_tokens int;
alter table public.jobs add column if not exists prompt_tokens int;
alter table public.jobs add column if not exists completion_tokens int;
