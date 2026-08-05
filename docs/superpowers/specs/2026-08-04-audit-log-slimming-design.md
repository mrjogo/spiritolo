# Audit log slimming — design

**Date:** 2026-08-04
**Status:** approved, not yet implemented

## Problem

Staging is at ~0.77 GB against a 0.5 GB Supabase free-tier limit. `audit.log`
is 302 MB of that — 38% of the database, and the single largest table.

Measured breakdown of its jsonb payload (detoasted):

| op | rows | payload |
|---|---:|---:|
| UPDATE | 46,024 | 167 MB |
| INSERT | 133,057 | 70 MB |
| DELETE | 0 | 0 |

The UPDATE bulk is `recipes`: each row stores the *full* `before` and `after`
images — including the fat Schema.org `source` JSON-LD — even when the update
touched one small unrelated field. The INSERT bulk is the same `source` blob a
third time, duplicating a row that already exists in `recipes`.

Table bloat is not the cause (`pages` and `recipes` sit at ~9% dead tuples,
everything else at 0%), so `VACUUM FULL` alone reclaims almost nothing.

## Non-goals

- **Rollback.** Still deferred, per
  [2026-07-19-taxonomy-harmonization-and-stage-rename-design.md](2026-07-19-taxonomy-harmonization-and-stage-rename-design.md).
  This change preserves the audit log's fitness as a future rollback substrate;
  it does not build rollback.
- **Automated retention.** Deliberately excluded — see the invariant below.
- **Moving the audit log to Railway.** Considered and deferred; revisit
  alongside `pages`. Notes retained under Alternatives.
- **Pruning `pages` rows.** `pages` is the index of every URL ever considered
  and stays complete.

## Design

### 1. Three payload shapes, by op

`audit.log_change()` narrows what it stores per op:

- **INSERT** → `after = NULL`. The *event* is kept in full (pk, ts,
  `actor_kind`, `actor_id`, `source`); only the payload is dropped.
- **UPDATE** → `before` and `after` narrowed to the `changed_keys` subset.
- **DELETE** → `before` kept in full, unchanged.

`pk` is computed from the full row image *before* the payload is narrowed, so
`coalesce(v_after ->> 'id', v_before ->> 'id')` keeps working. `changed_keys`
semantics are untouched.

A no-op UPDATE (fires the trigger, changes nothing) yields empty
`changed_keys`, so `jsonb_object_agg` over zero rows leaves `before`/`after`
NULL. Correct: nothing changed, nothing to record.

### 2. The reconstruction invariant (load-bearing)

Dropping the INSERT payload is safe because it is derivable:

> **inserted value = current row, reverse-applying each UPDATE's `before`
> image newest → oldest.** For a row since deleted, the DELETE's full `before`
> supplies it directly.

This holds only while a row's audit chain is unbroken. **Therefore no
date-based retention or pruning may be added** without also reinstating full
INSERT payloads — the two choices are coupled, and slim-and-keep-forever is
the coherent pairing. This must be recorded as a comment in the migration, not
just here.

Deletes stay fat because they close the loop and are rare — there are
currently zero DELETE rows in the entire log.

Worker writes are audited exactly as before. They are the *most* important to
capture, being unattended and at scale; `job_items` records that a job touched
an entity but never what values changed, so the UPDATE diff is the only place
that information exists.

### 3. Migration vs. script

The trigger change ships as a migration. **The one-time reclaim does not.**

Rewriting 179k existing rows inside a migration would roughly double
`audit.log` in dead tuples (~300 → ~600 MB peak) while the project is *already*
over quota, and would be a destructive data operation replaying against every
environment. `VACUUM FULL` additionally cannot run inside a transaction block,
so it could not live in a migration regardless.

So:

- **Migration** — trigger DDL only. Idempotent, replays cleanly on a fresh
  `supabase db reset`, no data operation. Also drops two unused `pages`
  indexes (below).
- **`scripts/slim-audit-log.sql`** — run by hand against staging. Batched by
  id range with a plain `VACUUM` between batches so space is reused rather than
  accumulated, then a single `VACUUM FULL audit.log` at the end. Idempotent:
  re-narrowing an already-narrow image is a no-op.

### 4. Unused `pages` indexes

Drop `pages_site_idx` (`btree (site)`) and `pages_denylist_idx`
(`btree (denylist) WHERE denylist`) — both plain non-unique, both at **0 scans**.
Worth ~4 MB; trivially re-addable if a future query needs them.

`pages_url_key` (71 MB, 557k scans) and `pages_pkey` (12 MB, 66k scans) are hot
scraper paths and stay.

### 5. Web

`AuditLogBrowser` detail relabels its two JSON panes to indicate updates show
the changed-key subset, and renders an explanatory note for inserts, whose
`after` is now null (payload not stored — derivable).

## Testing

Existing `test_audit_actor.py` asserts `ins["after"]["slug"] == "vodka"` and
must change. Added coverage:

- UPDATE stores only the changed keys in `before`/`after`
- INSERT stores a complete event with a null `after`
- DELETE stores the full `before`
- **round-trip:** insert → several updates → reverse-apply the stored diffs →
  assert recovery of the original inserted row. This test *is* the proof of
  the reconstruction invariant, and guards against a future change quietly
  breaking it.

Plus the existing `AuditLogBrowser.test.tsx` copy assertions.

## Expected result

`audit.log` 302 MB → **~40 MB**; database ~0.77 → **~0.50 GB**. Future growth
falls roughly 16x (~220 bytes per update row; a full 17k-recipe run ≈ 4 MB).

This lands *at* the free-tier line, not comfortably under it. `pages`
(183 MB, of which 90 MB is indexes) is the next lever for real headroom.

## Ordering

The manual reclaim decouples the two halves. No worker runs are in flight, so
nothing needs pausing and the `VACUUM FULL` lock is a non-issue.

1. Branch `claude/audit-slim-a4f1` off `main` — migration, tests, web copy, docs.
2. PR → `main`, merge.
3. Promote: PR **base `staging`, head `main`**, merged with a **merge commit,
   never squash**.
4. Migrations CI applies to staging — the trigger is now slim. Growth stops here.
5. Run `scripts/slim-audit-log.sql` against staging by hand.

Trigger-before-backfill matters: reversed, the reclaimed space would
immediately refill with fat rows until the code landed.

## Alternatives considered

- **Truncate the log.** Rejected: discards history for no benefit the slimming
  doesn't already deliver.
- **Skip auditing worker INSERTs.** Rejected — backwards. Worker writes are the
  silent ones and matter most. Dropping the redundant *payload* while keeping
  the *event* achieves the same saving without the blind spot.
- **Automated retention (`pg_cron`) / monthly partitioning (`pg_partman`).**
  Rejected: breaks the reconstruction invariant, and unnecessary once growth
  drops 16x.
- **Move `audit.log` to Railway.** Genuinely cleaner than moving `pages` —
  nothing joins it, nothing depends on it transactionally. Deferred because
  slimming alone removes it as a contributor. When revisited, the shape is a
  **local outbox + periodic drain**: the trigger keeps writing locally (single
  writer, all paths captured, no availability coupling) and a job ships batches
  to Railway and deletes them. Writing to Railway *synchronously from the
  trigger* via `postgres_fdw`/`dblink` is ruled out — it puts a remote
  dependency inside every content transaction. App-side logging from the worker
  is also ruled out: it loses the single-writer property that captures hand-SQL
  and the curation RPCs.
- **Moving `pages` to Railway.** Deferred. `_eligible_base` joins
  `pages`/`recipes`/`taxonomy_nodes` against `job_items` in a single query to
  compute per-stage status for run assembly; splitting those across databases
  breaks that join and means rewiring run assembly, not just relocating a table.
