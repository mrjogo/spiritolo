-- Audit log: store diffs, not full row images.
--
-- audit.log had grown to 302 MB — 38% of the database and over the Supabase
-- free-tier ceiling. Measured, its payload was 167 MB of UPDATE images and
-- 70 MB of INSERT images, dominated by `recipes`: every row stored the full
-- Schema.org `source` JSON-LD in both `before` and `after`, even when the
-- update touched one unrelated field, and again on insert — a third copy of a
-- blob that already lives in recipes.source.
--
-- Three shapes, by op:
--   INSERT → after = NULL. The EVENT is kept in full (pk, ts, actor, source);
--            only the payload is dropped.
--   UPDATE → before/after narrowed to the changed_keys subset.
--   DELETE → before kept whole.
--
-- RECONSTRUCTION INVARIANT (load-bearing — read before changing this):
--   inserted value = current row, reverse-applying each UPDATE's `before`
--   image newest -> oldest. For a since-deleted row, the DELETE's full
--   `before` supplies it directly.
-- That is what makes dropping the INSERT payload lossless. It holds ONLY
-- while a row's audit chain is unbroken, so DO NOT add date-based retention
-- or pruning without reinstating full INSERT payloads — the two choices are
-- coupled, and slim-and-keep-forever is the coherent pairing. The executable
-- proof is ingredients/tests/test_audit_payload_shape.py::
-- test_insert_payload_is_reconstructable.
--
-- Unchanged: the actor model, the single-writer property, changed_keys
-- semantics, and the fact that WORKER writes are audited exactly like human
-- ones. Worker writes are the unattended ones and matter most; job_items
-- records THAT a job touched an entity but never WHAT values changed, so the
-- UPDATE diff is the only place that information exists.
--
-- This migration is DDL only. Reclaiming the existing 302 MB is a one-time
-- operation in scripts/slim-audit-log.sql, run by hand against staging —
-- rewriting 179k rows inside a migration would roughly double the table in
-- dead tuples while the project is already over quota, and VACUUM FULL cannot
-- run inside a transaction block.

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
  -- Resolved from the FULL images, before either is narrowed below.
  v_pk     text  := coalesce(v_after ->> 'id', v_before ->> 'id');
  v_keys   text[];
begin
  if v_uid is not null then          -- ran under a user JWT → admin RPC / manual edit
    v_kind := 'human';  v_actor := v_uid;
  elsif v_job is not null then       -- worker set app.job_id at the top of its job txn
    v_kind := 'worker'; v_actor := v_job;
  else                               -- migration / reaper / seed / hand-SQL
    v_kind := 'system'; v_actor := null;
  end if;

  if tg_op = 'UPDATE' then
    select array_agg(key order by key) into v_keys
    from jsonb_each(v_after)
    where v_after -> key is distinct from v_before -> key;

    -- Narrow before FIRST, then after: v_after must still be whole while it is
    -- read here. An empty/NULL v_keys aggregates over zero rows -> NULL, which
    -- is the correct record of a no-op update.
    v_before := (select jsonb_object_agg(k, v_before -> k)
                 from unnest(coalesce(v_keys, '{}'::text[])) k);
    v_after  := (select jsonb_object_agg(k, v_after -> k)
                 from unnest(coalesce(v_keys, '{}'::text[])) k);
  elsif tg_op = 'INSERT' then
    v_after := null;                 -- derivable; see the invariant above
  end if;

  insert into audit.log (
    table_name, pk, op, actor_kind, actor_id, source,
    before, after, changed_keys
  )
  values (
    tg_table_name, v_pk, left(tg_op, 1),
    v_kind, v_actor, v_src,
    v_before, v_after, v_keys
  );
  return null;   -- AFTER trigger: return value is ignored
end;
$$;

comment on column audit.log.before is
  'UPDATE: the changed_keys subset of the pre-image. DELETE: the full row. NULL on INSERT.';
comment on column audit.log.after is
  'UPDATE: the changed_keys subset of the post-image. NULL on INSERT (payload is derivable) and on DELETE.';

-- Unused indexes on pages: both plain non-unique, both at zero scans since the
-- table was created. pages_url_key (557k scans) and pages_pkey (66k) are hot
-- scraper paths and stay. Trivially re-addable if a future query needs them.
drop index if exists public.pages_site_idx;
drop index if exists public.pages_denylist_idx;
