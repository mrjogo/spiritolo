-- Postgres-as-queue (WS-B22), part 3 of 3: the enqueue_job / approve_job RPCs.
--
-- These two SECURITY DEFINER functions are the ONLY write path onto jobs (RLS is
-- deny-all). They reuse the taxonomy-curation RPC pattern exactly: SECURITY
-- DEFINER + `set search_path = ''` + a public.is_admin() gate that raises 42501
-- for non-admins, with EXECUTE granted to `authenticated` only (revoked from
-- public, so anon cannot call them and cannot INSERT directly either).
--
-- All object references are schema-qualified because search_path is empty.

------------------------------------------------------------------------
-- enqueue_job(...) — insert a scoped job, admin only
------------------------------------------------------------------------
-- Free stages (requires_approval=false) go straight to 'queued'. Metered stages
-- (requires_approval=true) go to 'awaiting_approval' carrying a cost estimate;
-- an admin must approve_job() before the worker can claim them. created_by is
-- stamped from auth.uid() so the audit trail attributes the enqueue to a human.
create or replace function public.enqueue_job(
  p_stage               text,
  p_kind                text default 'run',
  p_payload             jsonb default '{}'::jsonb,
  p_version             text default null,
  p_requires_approval   boolean default false,
  p_cost_estimate_cents integer default null,
  p_max_cost_cents      integer default null
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  insert into public.jobs (
    stage, kind, payload, version, requires_approval,
    cost_estimate_cents, max_cost_cents, state, created_by
  )
  values (
    p_stage,
    p_kind,
    coalesce(p_payload, '{}'::jsonb),
    p_version,
    coalesce(p_requires_approval, false),
    p_cost_estimate_cents,
    p_max_cost_cents,
    case
      when coalesce(p_requires_approval, false)
        then 'awaiting_approval'::public.job_state
      else 'queued'::public.job_state
    end,
    auth.uid()
  )
  returning id into v_id;

  return v_id;
end;
$$;

revoke all on function public.enqueue_job(text, text, jsonb, text, boolean, integer, integer) from public;
grant execute on function public.enqueue_job(text, text, jsonb, text, boolean, integer, integer) to authenticated;

------------------------------------------------------------------------
-- approve_job(id) — clear a metered job for claiming, admin only
------------------------------------------------------------------------
-- Flips approved=true / approved_by=auth.uid() / state='queued' on an
-- awaiting_approval job. A no-op on a job that has already advanced (claimed/
-- running/terminal) — approval only gates the pre-claim transition, so an
-- approve that races a claim can't drag a running job back to queued.
create or replace function public.approve_job(p_id bigint)
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

  select state into v_state from public.jobs where id = p_id;
  if v_state is null then
    raise exception 'job % not found', p_id using errcode = '23503';
  end if;

  -- Only an awaiting_approval job is affected; everything else is a no-op.
  if v_state <> 'awaiting_approval'::public.job_state then
    return;
  end if;

  update public.jobs
  set approved    = true,
      approved_by = auth.uid(),
      approved_at = now(),
      state       = 'queued'::public.job_state
  where id = p_id;
end;
$$;

revoke all on function public.approve_job(bigint) from public;
grant execute on function public.approve_job(bigint) to authenticated;
