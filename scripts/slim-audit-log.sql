-- One-time reclaim: rewrite existing audit.log rows into the slim shapes that
-- 20260804090000_audit_slim_payloads.sql made the trigger produce.
--
-- WHY THIS IS NOT A MIGRATION
--   * It rewrites ~179k rows, roughly doubling the table in dead tuples
--     (~300 -> ~600 MB peak) while the project is already over its disk quota.
--     Batching + plain VACUUM between batches keeps the peak to one batch.
--   * VACUUM FULL cannot run inside a transaction block, and Supabase runs
--     each migration in one.
--   * It is a destructive data operation; replaying it against every
--     environment on `supabase db reset` is not wanted.
--
-- SAFE TO RE-RUN. Narrowing an already-narrow image is a no-op, and the
-- INSERT pass is guarded on `after is not null`.
--
-- RUN IT AFTER the migration has landed on staging, not before — otherwise the
-- reclaimed space refills with full images until the new trigger deploys.
--
-- Usage (from a host that can reach staging; expects no worker runs in flight):
--   psql "$SUPABASE_STAGING_DB_URL" -f scripts/slim-audit-log.sql
--
-- Expect audit.log to go from ~302 MB to ~40 MB.

\timing on

select pg_size_pretty(pg_total_relation_size('audit.log')) as size_before;

-- Pass 1 — drop redundant INSERT payloads.
-- Batched by id so each statement's dead tuples stay bounded; VACUUM between
-- batches returns that space to the table's free space map for reuse.
do $$
declare
  v_lo bigint;
  v_hi bigint;
  v_batch constant bigint := 20000;
begin
  select min(id), max(id) into v_lo, v_hi from audit.log where op = 'I';
  while v_lo is not null and v_lo <= v_hi loop
    update audit.log
       set after = null
     where op = 'I'
       and after is not null
       and id >= v_lo and id < v_lo + v_batch;
    raise notice 'inserts: cleared through id %', v_lo + v_batch;
    v_lo := v_lo + v_batch;
  end loop;
end $$;

vacuum audit.log;

-- Pass 2 — narrow UPDATE images to their changed_keys subset.
do $$
declare
  v_lo bigint;
  v_hi bigint;
  v_batch constant bigint := 5000;
begin
  select min(id), max(id) into v_lo, v_hi from audit.log where op = 'U';
  while v_lo is not null and v_lo <= v_hi loop
    update audit.log l
       set before = (select jsonb_object_agg(k, l.before -> k)
                     from unnest(coalesce(l.changed_keys, '{}'::text[])) k),
           after  = (select jsonb_object_agg(k, l.after -> k)
                     from unnest(coalesce(l.changed_keys, '{}'::text[])) k)
     where l.op = 'U'
       and l.id >= v_lo and l.id < v_lo + v_batch
       and (l.before is not null or l.after is not null);
    raise notice 'updates: narrowed through id %', v_lo + v_batch;
    v_lo := v_lo + v_batch;
  end loop;
end $$;

vacuum audit.log;

-- Compact for real: hands the freed space back to the OS. Takes an ACCESS
-- EXCLUSIVE lock, so run it with no worker jobs in flight. Peak disk during
-- the rewrite is old size + new size.
vacuum full audit.log;

select pg_size_pretty(pg_total_relation_size('audit.log')) as size_after,
       pg_size_pretty(pg_database_size(current_database())) as database_size;
