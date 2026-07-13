-- Audit log: the generic trigger + its attachments.
--
-- audit.log_change() is the SINGLE audit writer. The actor distinction falls
-- out with no side channel:
--   * user JWT present (auth.uid() non-null)  → 'human', actor_id = <uid>
--   * app.job_id GUC set by the worker        → 'worker', actor_id = <job id>
--   * neither (migration / reaper / seed / hand-SQL) → 'system', actor_id null
-- The writer sets app.job_id / app.source with SET LOCAL (transaction-scoped);
-- this trigger only READS them (via current_setting(..., true)). Because the
-- trigger is the only thing that writes audit.log, every path — hand-SQL, the
-- service-role worker (ingredients/worker/actor_context.set_job_context), and
-- the admin curation RPCs (which run under the user's JWT) — is captured
-- uniformly with no double-logging and no per-RPC audit code.

create or replace function audit.log_change() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid    text  := (select auth.uid())::text;
  v_job    text  := nullif(current_setting('app.job_id', true), '');
  v_src    text  := coalesce(nullif(current_setting('app.source', true), ''), 'unknown');
  v_kind   text;
  v_actor  text;
  v_before jsonb := case when tg_op <> 'INSERT' then to_jsonb(old) end;
  v_after  jsonb := case when tg_op <> 'DELETE' then to_jsonb(new) end;
begin
  if v_uid is not null then          -- ran under a user JWT → admin RPC / manual edit
    v_kind := 'human';  v_actor := v_uid;
  elsif v_job is not null then       -- worker set app.job_id at the top of its job txn
    v_kind := 'worker'; v_actor := v_job;
  else                               -- migration / reaper / seed / hand-SQL
    v_kind := 'system'; v_actor := null;
  end if;

  insert into audit.log (
    table_name, pk, op, actor_kind, actor_id, source,
    before, after, changed_keys
  )
  values (
    tg_table_name,
    coalesce(v_after ->> 'id', v_before ->> 'id'),
    left(tg_op, 1),
    v_kind, v_actor, v_src,
    v_before, v_after,
    case when tg_op = 'UPDATE' then (
      select array_agg(key order by key)
      from jsonb_each(v_after)
      where v_after -> key is distinct from v_before -> key
    ) end
  );
  return null;   -- AFTER trigger: return value is ignored
end;
$$;

-- Attach to the curated tables that EXIST today and matter for human-edit
-- provenance. Each has a scalar bigint `id` PK, so pk := to_jsonb(row)->>'id'
-- is well-defined.
--
-- NOTE: the relational recipe tables (recipes / recipe_ingredients /
-- recipe_steps) are not built yet. When they land, attach this SAME trigger to
-- each of them (one `create trigger audit_<table> after insert or update or
-- delete on public.<table> for each row execute function audit.log_change();`)
-- so pipeline writes and manual recipe edits are captured identically — no new
-- function, just the attachment.
--
-- Composite-PK reference tables (taxonomy_edges / taxonomy_aliases /
-- cocktail_aliases) are intentionally NOT row-audited: their curation RPCs
-- replace-all edge/alias sets under an audited taxonomy_nodes action, so the
-- node-level audit row is already the meaningful record.

create trigger audit_taxonomy_nodes
  after insert or update or delete on public.taxonomy_nodes
  for each row execute function audit.log_change();

create trigger audit_taxonomy_proposals
  after insert or update or delete on public.taxonomy_proposals
  for each row execute function audit.log_change();

create trigger audit_recipegf_proposals
  after insert or update or delete on public.recipegf_proposals
  for each row execute function audit.log_change();
