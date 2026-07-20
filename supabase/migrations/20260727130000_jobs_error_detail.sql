-- A failed job records a short human-readable reason alongside the coded
-- error_code, so /ops can show WHY a run failed instead of a bare
-- "stage_error". The worker writes it in _finalize_failed (the full traceback
-- goes to the worker log); it stays null on success. Exposed on the `runs`
-- view alongside the rest of the run cockpit fields in a later migration.
alter table public.jobs add column if not exists error_detail text;
