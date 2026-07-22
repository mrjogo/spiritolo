-- Cancellation states for a run. `cancelling` is the transient "stop requested"
-- state the worker sees and honors cooperatively; `cancelled` is terminal.
-- Added in their own migration because Postgres can't use a new enum value in
-- the same transaction that introduced it (the cancel_run RPC that references
-- them lives in the next migration).
alter type public.job_state add value if not exists 'cancelling';
alter type public.job_state add value if not exists 'cancelled';
