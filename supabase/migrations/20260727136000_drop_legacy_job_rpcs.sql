-- Drop the legacy enqueue_job / approve_job SECURITY DEFINER RPCs. They were the
-- pre-explicit-runs write + approval path, superseded by create_run /
-- add_run_items / start_run, and have no caller in the web app or the pipeline
-- (verified by grep) — but they were never dropped, leaving two live,
-- authenticated write functions that no longer fit the run model. Removing them
-- shrinks the write surface.
--
-- The `requires_approval` / `approved` columns stay: the claim gate
-- (queue/claim.py) still reads them, and start_run still sets them. Only the two
-- orphaned RPCs go. (The now-unwritten `awaiting_approval` enum value is left in
-- place — enum values can't be dropped cleanly and it's harmless.)
drop function if exists public.enqueue_job(text, text, jsonb, text, boolean, integer, integer);
drop function if exists public.approve_job(bigint);
