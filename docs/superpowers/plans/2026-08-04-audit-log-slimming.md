# Audit Log Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `audit.log` from 302 MB to ~40 MB by storing only changed-key diffs on UPDATE and dropping the redundant INSERT payload, without losing the ability to reconstruct any historical row.

**Architecture:** One `create or replace` of `audit.log_change()` narrows what the trigger stores, per op. A separate hand-run SQL script reclaims the existing rows on staging (kept out of migrations because it is a destructive data operation and because `VACUUM FULL` cannot run in a transaction). The `/ops` audit browser gets copy changes to reflect the new shapes.

**Tech Stack:** PostgreSQL 17 (plpgsql triggers), Supabase migrations, Python 3.11 + pytest + psycopg (DB-integration tests), Vite/React/TypeScript + Vitest.

## Global Constraints

- Spec: [docs/superpowers/specs/2026-08-04-audit-log-slimming-design.md](../specs/2026-08-04-audit-log-slimming-design.md). Read it before starting.
- Branch: `claude/audit-slim-a4f1`. Never push elsewhere.
- **The reconstruction invariant is load-bearing:** inserted value = current row with each UPDATE's `before` image reverse-applied newest → oldest. Never add date-based retention or pruning to `audit.log` without reinstating full INSERT payloads.
- DELETE rows keep the **full** `before` image. Only UPDATE and INSERT change.
- Worker writes are audited exactly as before — no actor-based filtering anywhere.
- Migration filename: `supabase/migrations/20260804090000_audit_slim_payloads.sql` (next in sequence after `20260727137000_drop_pages_fetch_meta.sql`).
- DB tests need `TEST_DB_URL` set; they skip cleanly without it. The `ingredients` conftest auto-applies new `supabase/migrations/*.sql` at session start, so adding the migration file is enough for tests to see it.
- Python tests: `cd ingredients && uv run --extra dev pytest`. Web: `cd web && npm test`.
- Do not run `npm install` in `web/` — it rewrites `package-lock.json` under the wrong npm major. No dependencies change in this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `supabase/migrations/20260804090000_audit_slim_payloads.sql` (create) | Replaces `audit.log_change()` with the three-shapes-by-op version; drops two unused `pages` indexes. |
| `ingredients/tests/test_audit_payload_shape.py` (create) | Owns the new payload-shape + reconstruction round-trip coverage. |
| `ingredients/tests/test_audit_actor.py` (modify) | One assertion updated: INSERT `after` is now null. |
| `scripts/slim-audit-log.sql` (create) | One-time hand-run reclaim for staging. |
| `web/src/pages/ops/AuditLogBrowser.tsx` (modify) | Detail-pane copy for the new shapes. |
| `web/src/pages/ops/AuditLogBrowser.test.tsx` (modify) | Coverage for that copy. |

Tasks 1, 2, and 3 touch disjoint files and can be implemented in parallel.

---

### Task 1: Slim trigger + unused index drops

**Files:**
- Create: `supabase/migrations/20260804090000_audit_slim_payloads.sql`
- Create: `ingredients/tests/test_audit_payload_shape.py`
- Modify: `ingredients/tests/test_audit_actor.py:141-144`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the `audit.log` row shapes that Task 2's backfill and Task 3's UI must match — INSERT `after IS NULL`, UPDATE `before`/`after` keyed exactly by `changed_keys`, DELETE `before` full.

- [ ] **Step 1: Write the failing tests**

Create `ingredients/tests/test_audit_payload_shape.py`:

```python
"""Payload-shape tests for the audit log.

The log stores three shapes, by op:

- INSERT → ``after`` is NULL. The event is kept; the payload is dropped as
  redundant (see the reconstruction invariant below).
- UPDATE → ``before``/``after`` narrowed to the ``changed_keys`` subset.
- DELETE → ``before`` kept in full, closing the loop.

RECONSTRUCTION INVARIANT: the inserted value is recoverable as the current row
with each UPDATE's ``before`` image reverse-applied newest → oldest. This is
what makes dropping the INSERT payload safe, and it only holds while a row's
audit chain is unbroken — so no date-based retention may be added without
reinstating full INSERT payloads. ``test_insert_payload_is_reconstructable``
is the executable proof.

Runs against ``TEST_DB_URL``.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


@pytest.fixture
def clean(db_conn):
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    db_conn.execute("truncate table audit.log restart identity")
    db_conn.execute("delete from taxonomy_nodes")
    return db_conn


def _insert_node(conn, slug: str, name: str) -> int:
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
        (slug, name),
    ).fetchone()[0]


def _rows(conn, pk) -> list[dict]:
    """Every audit row for a taxonomy_nodes pk, oldest first."""
    cols = ["id", "op", "before", "after", "changed_keys"]
    res = conn.execute(
        f"select {', '.join(cols)} from audit.log "
        "where table_name = 'taxonomy_nodes' and pk = %s order by id",
        (str(pk),),
    ).fetchall()
    return [dict(zip(cols, r)) for r in res]


def test_insert_stores_event_without_payload(clean):
    conn = clean
    nid = _insert_node(conn, "mezcal", "Mezcal")

    (ins,) = _rows(conn, nid)
    assert ins["op"] == "I"
    assert ins["after"] is None, "INSERT payload is redundant and must not be stored"
    assert ins["before"] is None
    # The EVENT survives in full — only the payload is dropped.
    row = conn.execute(
        "select actor_kind, source, pk from audit.log where id = %s", (ins["id"],)
    ).fetchone()
    assert row[0] == "system"
    assert row[1]
    assert row[2] == str(nid)


def test_update_stores_only_changed_keys(clean):
    conn = clean
    nid = _insert_node(conn, "amaro", "Amaro")
    conn.execute("truncate table audit.log restart identity")

    conn.execute(
        "update taxonomy_nodes set display_name = 'Amaro Nonino' where id = %s", (nid,)
    )

    (upd,) = _rows(conn, nid)
    assert upd["op"] == "U"
    keys = set(upd["changed_keys"])
    assert keys == {"display_name", "updated_at"}, upd["changed_keys"]
    # before/after carry EXACTLY the changed keys — no slug, no id, no created_at.
    assert set(upd["before"]) == keys
    assert set(upd["after"]) == keys
    assert upd["before"]["display_name"] == "Amaro"
    assert upd["after"]["display_name"] == "Amaro Nonino"


def test_delete_keeps_full_before(clean):
    conn = clean
    nid = _insert_node(conn, "pisco", "Pisco")
    conn.execute("truncate table audit.log restart identity")

    conn.execute("delete from taxonomy_nodes where id = %s", (nid,))

    (dele,) = _rows(conn, nid)
    assert dele["op"] == "D"
    assert dele["after"] is None
    # Full image, not a subset — deletes close the reconstruction loop.
    assert dele["before"]["slug"] == "pisco"
    assert dele["before"]["display_name"] == "Pisco"
    assert "created_at" in dele["before"]


def test_noop_update_records_nothing_changed(clean):
    conn = clean
    nid = _insert_node(conn, "rhum", "Rhum")
    conn.execute("truncate table audit.log restart identity")

    # public.set_updated_at() writes now(), which is TRANSACTION-scoped — so
    # inside one transaction the second update writes an identical updated_at
    # and changes nothing at all. That is the only way to reach the empty
    # changed_keys path, which must leave before/after NULL rather than {}.
    with conn.transaction():
        conn.execute(
            "update taxonomy_nodes set display_name = 'Rum' where id = %s", (nid,)
        )
        conn.execute(
            "update taxonomy_nodes set display_name = 'Rum' where id = %s", (nid,)
        )

    rows = _rows(conn, nid)
    assert len(rows) == 2
    noop = rows[-1]
    assert noop["op"] == "U"
    assert not noop["changed_keys"]
    assert noop["before"] is None
    assert noop["after"] is None


def test_insert_payload_is_reconstructable(clean):
    """The executable proof of the reconstruction invariant.

    Insert, mutate repeatedly, then rebuild the original inserted row from the
    current state plus the stored UPDATE diffs alone — never reading the
    INSERT payload, which no longer exists.
    """
    conn = clean
    nid = _insert_node(conn, "cachaca", "Cachaca")
    original = conn.execute(
        "select to_jsonb(t.*) from taxonomy_nodes t where id = %s", (nid,)
    ).fetchone()[0]

    conn.execute(
        "update taxonomy_nodes set display_name = 'Cachaça' where id = %s", (nid,)
    )
    conn.execute(
        "update taxonomy_nodes set status = 'provisional' where id = %s", (nid,)
    )
    conn.execute(
        "update taxonomy_nodes set display_name = 'Cachaça (BR)' where id = %s", (nid,)
    )

    current = conn.execute(
        "select to_jsonb(t.*) from taxonomy_nodes t where id = %s", (nid,)
    ).fetchone()[0]

    # Reverse-apply each UPDATE's `before` image, newest → oldest.
    reconstructed = dict(current)
    for row in reversed(_rows(conn, nid)):
        if row["op"] == "U" and row["before"]:
            reconstructed.update(row["before"])

    assert reconstructed == original
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ingredients && uv run --extra dev pytest tests/test_audit_payload_shape.py -v`

Expected: FAIL. `test_insert_stores_event_without_payload` fails on `assert ins["after"] is None` (the current trigger stores the full row), and `test_update_stores_only_changed_keys` fails on `set(upd["before"]) == keys` (currently the full image).

If instead every test SKIPS, `TEST_DB_URL` is unset — export it per CLAUDE.md before continuing. Do not proceed on skips.

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260804090000_audit_slim_payloads.sql`:

```sql
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
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd ingredients && uv run --extra dev pytest tests/test_audit_payload_shape.py -v`

Expected: 5 passed. The conftest applies the new migration to `TEST_DB_URL` on session start.

- [ ] **Step 5: Fix the one stale assertion in the existing actor tests**

In `ingredients/tests/test_audit_actor.py`, replace lines 141-144:

```python
    ins = _latest_audit(conn, "taxonomy_nodes", nid)
    assert ins["op"] == "I"
    assert ins["before"] is None
    assert ins["after"] is not None and ins["after"]["slug"] == "vodka"
```

with:

```python
    ins = _latest_audit(conn, "taxonomy_nodes", nid)
    assert ins["op"] == "I"
    assert ins["before"] is None
    # Payload dropped as derivable; the event itself is what this test guards.
    assert ins["after"] is None
```

Also update the module docstring line 11, from:

```
Plus: INSERT/UPDATE/DELETE all captured with the right op + before/after.
```

to:

```
Plus: INSERT/UPDATE/DELETE all captured with the right op. Payload SHAPES
(insert has no after, update is narrowed to changed_keys) are covered in
test_audit_payload_shape.py.
```

- [ ] **Step 6: Run the full audit suite**

Run: `cd ingredients && uv run --extra dev pytest tests/test_audit_actor.py tests/test_audit_changed_keys.py tests/test_audit_schema.py tests/test_audit_payload_shape.py -v`

Expected: all pass. `test_audit_changed_keys.py` and `test_audit_schema.py` should need no edits — they assert `changed_keys` content and column types, both unchanged.

- [ ] **Step 7: Run the whole ingredients suite for regressions**

Run: `cd ingredients && uv run --extra dev pytest`

Expected: no new failures. Note the migration dropped two `pages` indexes; if any test asserts on `pages` index presence, that is a real finding — report it rather than deleting the assertion.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/20260804090000_audit_slim_payloads.sql \
        ingredients/tests/test_audit_payload_shape.py \
        ingredients/tests/test_audit_actor.py
git commit -m "Store audit diffs instead of full row images; drop unused pages indexes"
```

---

### Task 2: One-time reclaim script

**Files:**
- Create: `scripts/slim-audit-log.sql`

**Interfaces:**
- Consumes: the row shapes Task 1 produces — INSERT `after IS NULL`, UPDATE `before`/`after` keyed by `changed_keys`.
- Produces: nothing other tasks consume. Hand-run against staging after the migration lands.

This task has no test cycle: it is an operational script run once against a database this repo's test suite never touches. Correctness comes from it being idempotent and from mirroring Task 1's shapes exactly.

- [ ] **Step 1: Write the script**

Create `scripts/slim-audit-log.sql`:

```sql
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
```

- [ ] **Step 2: Verify it parses without executing the data passes**

There is no staging access from this branch, so check syntax only. Against any local Postgres with the schema applied (`TEST_DB_URL` works — its `audit.log` is empty or tiny, so the passes are no-ops):

Run: `psql "$TEST_DB_URL" -f scripts/slim-audit-log.sql`

Expected: completes with no syntax errors, printing `size_before` / `size_after` / `database_size`. On an empty log both `do` blocks exit immediately because `min(id)` is NULL.

If `TEST_DB_URL` is unset, skip this step and say so explicitly in the task report rather than claiming the script was verified.

- [ ] **Step 3: Commit**

```bash
git add scripts/slim-audit-log.sql
git commit -m "Add one-time audit.log reclaim script"
```

---

### Task 3: Audit browser copy for the new shapes

**Files:**
- Modify: `web/src/pages/ops/AuditLogBrowser.tsx:150-157`
- Modify: `web/src/pages/ops/AuditLogBrowser.test.tsx`

**Interfaces:**
- Consumes: the row shapes Task 1 produces. `AuditLogDetailRow` already types `before`/`after` as `unknown` and `changed_keys` as `string[] | null`; no type changes are needed.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/pages/ops/AuditLogBrowser.test.tsx`, inside the existing top-level `describe` block (match the file's existing style for rendering + selecting a row — reuse `mockSupabase`, `renderBrowser`, and `makeClient`):

```tsx
  it('explains that insert rows store no payload', async () => {
    const row = {
      id: 7, ts: '2026-08-04T00:00:00Z', table_name: 'recipes', pk: '99',
      op: 'I', actor_kind: 'worker', actor_id: '42', source: 'job:extract-recipe',
    };
    mockSupabase([row], { ...row, before: null, after: null, changed_keys: null });
    const user = userEvent.setup();
    renderBrowser(makeClient());

    await user.click(await screen.findByText('recipes'));

    expect(await screen.findByText(/payload not stored/i)).toBeInTheDocument();
  });

  it('labels update images as the changed-key subset', async () => {
    const row = {
      id: 8, ts: '2026-08-04T00:00:00Z', table_name: 'recipes', pk: '99',
      op: 'U', actor_kind: 'worker', actor_id: '42', source: 'job:extract-recipe',
    };
    mockSupabase([row], {
      ...row,
      before: { title: 'Old' },
      after: { title: 'New' },
      changed_keys: ['title'],
    });
    const user = userEvent.setup();
    renderBrowser(makeClient());

    await user.click(await screen.findByText('recipes'));

    expect(await screen.findByText(/before \(changed keys only\)/i)).toBeInTheDocument();
    expect(screen.getByText(/after \(changed keys only\)/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- AuditLogBrowser`

Expected: both new tests FAIL — no "payload not stored" text exists, and the panes are labelled bare `before` / `after`.

- [ ] **Step 3: Update the detail pane**

In `web/src/pages/ops/AuditLogBrowser.tsx`, replace the two `JsonView` lines (currently 156-157):

```tsx
      <JsonView value={row.before} name="before" />
      <JsonView value={row.after} name="after" />
```

with:

```tsx
      {row.op === 'I' ? (
        <p style={{ fontSize: 12, opacity: 0.7 }}>
          Row created — payload not stored. It is derivable from the current row by
          reverse-applying later updates.
        </p>
      ) : (
        <>
          <JsonView
            value={row.before}
            name={row.op === 'U' ? 'before (changed keys only)' : 'before'}
          />
          <JsonView
            value={row.after}
            name={row.op === 'U' ? 'after (changed keys only)' : 'after'}
          />
        </>
      )}
```

Update the component's leading comment (currently line 54-56) to match:

```tsx
// The audit_log_public browser: actor legibility is the point (human vs
// worker vs system, and the source that triggered the write), plus a
// before/after diff on drill-down. Updates store only the changed-key
// subset; inserts store no payload at all (it is derivable) — so the detail
// pane labels each shape rather than implying a full row image.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- AuditLogBrowser`

Expected: all pass, including the file's pre-existing tests.

- [ ] **Step 5: Run the full web suite**

Run: `cd web && npm test`

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/ops/AuditLogBrowser.tsx web/src/pages/ops/AuditLogBrowser.test.tsx
git commit -m "Label audit detail panes for slim diff shapes"
```

---

### Task 4: Documentation

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the shapes and invariant from Task 1.
- Produces: nothing.

- [ ] **Step 1: Record the invariant where the next reader will look**

`CLAUDE.md`'s **Data model** section describes `jobs`/`job_items` and ends with a parenthetical about the audit log being the rollback substrate. Replace that parenthetical:

```
(The append-only audit log captures each row's before+after tagged with the job id — the intended substrate for a future run rollback, which is not yet built.)
```

with:

```
(The append-only audit log captures each mutation tagged with the job id — the intended substrate for a future run rollback, which is not yet built. It stores *diffs*, not full row images: an UPDATE keeps only the `changed_keys` subset, an INSERT keeps the event with no payload, a DELETE keeps the whole row. That is lossless because the inserted value is recoverable from the current row by reverse-applying each UPDATE's `before` image newest → oldest — an invariant that holds only while a row's audit chain is unbroken, so **do not add retention or pruning to `audit.log`** without reinstating full INSERT payloads. One-time reclaim for an already-fat log: `scripts/slim-audit-log.sql`.)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Document the audit log diff shapes and reconstruction invariant"
```

---

## Verification

After all tasks:

- [ ] `cd ingredients && uv run --extra dev pytest` — passes
- [ ] `cd web && npm test` — passes
- [ ] `git log --oneline main..HEAD` shows the task commits
- [ ] Confirm `git diff main --stat` touches only: the new migration, `scripts/slim-audit-log.sql`, the two audit test files, `AuditLogBrowser.{tsx,test.tsx}`, `CLAUDE.md`, and the spec/plan docs

Then open the PR against `main` per CLAUDE.md (optional one-paragraph description, up to 8 bullets, no sections, no test plan).

**Not part of this plan — operator steps after merge:**

1. Promote: PR **base `staging`, head `main`**, merged with a **merge commit, never squash**.
2. Migrations CI applies to staging; the trigger goes slim and growth stops.
3. Run `scripts/slim-audit-log.sql` against staging by hand.
