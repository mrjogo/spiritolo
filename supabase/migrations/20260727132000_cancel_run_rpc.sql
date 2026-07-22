-- cancel_run(job_id): stop a run from /ops.
--
--   draft / queued  -> 'cancelled' immediately (no worker has it; nothing to
--                      unwind — items stay pending, the run just won't be run).
--   claimed/running -> 'cancelling' (a cooperative stop request). The worker's
--                      cancel-watcher sees it, signals the stage to stop at the
--                      next item boundary, and finalizes the run to 'cancelled'
--                      with whatever it already processed preserved.
--   terminal / already cancelling -> idempotent no-op.
--
-- Same shape as the other run RPCs: SECURITY DEFINER, empty search_path, an
-- is_admin() gate, EXECUTE revoked from public and granted to authenticated.
create or replace function public.cancel_run(job_id bigint)
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

  select state into v_state
  from public.jobs
  where id = cancel_run.job_id
  for update;

  if v_state is null then
    raise exception 'run % not found', cancel_run.job_id using errcode = '23503';
  end if;

  if v_state in ('draft', 'queued') then
    update public.jobs
    set state = 'cancelled'::public.job_state, finished_at = now()
    where id = cancel_run.job_id;
  elsif v_state in ('claimed', 'running') then
    update public.jobs
    set state = 'cancelling'::public.job_state
    where id = cancel_run.job_id;
  end if;
  -- terminal ('done'/'succeeded'/'failed'/'cancelled') or already 'cancelling':
  -- nothing to do.
end;
$$;

revoke all on function public.cancel_run(bigint) from public;
grant execute on function public.cancel_run(bigint) to authenticated;
