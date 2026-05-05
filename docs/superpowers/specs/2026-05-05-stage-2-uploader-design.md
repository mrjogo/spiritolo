# Stage 2 — Local-edit / staging-upload uploader

Design for the `scripts/upload-to-staging.py` workflow: a sidecar-anchored,
serializable-transaction uploader that pushes a dirty-row diff from a local
Supabase to staging, with mandatory protections against schema drift,
mismatched targets, and concurrent staging writes.

This spec supersedes the Stage 2 sketch in [WORKFLOW_PLAN.md](../../../WORKFLOW_PLAN.md).
Where the two disagree, this spec wins.

## Goals

1. Make "restore staging dump locally → run pipelines on the local copy →
   push the diff back to staging" a single, low-ceremony command.
2. Refuse to run if any input is suspect (wrong staging target, drifted
   schema, stale dump, concurrent staging writes).
3. Either fully apply the diff or fully abort. Never leave staging in a
   half-pushed state.
4. Preserve the existing `pg_restore` flow as-is. The dump file remains a
   standalone artifact; the new sidecar is additive.

## Non-goals

- Trigger-based dirty tracking. Timestamp-diff is sufficient; no current
  pipeline issues `DELETE`s.
- Multi-writer / multi-machine coordination. Single human writer plus one
  AI agent at a time, honor system on "don't edit staging during a work
  session."
- Automated reconciliation when staleness fires. The script aborts with a
  clear message; the operator re-takes a backup and starts the work session
  over.
- Schema-only DDL diffing of live staging. Migration-list equality is the
  defended invariant; full DDL drift detection (option C from brainstorm)
  is out of scope.

## Pre-work — two schema migrations

### Migration 1 — `updated_at` (already shipped)

Adds an auto-maintained `updated_at TIMESTAMPTZ` column and `BEFORE UPDATE`
trigger to every public-schema table. Lives at
[supabase/migrations/20260505040811_add_updated_at.sql](../../../supabase/migrations/20260505040811_add_updated_at.sql).
Required so the uploader can compute the dirty set.

### Migration 2 — Deferrable FKs for the recipes / recipe_clusters cycle

**Why.** `recipes.cluster_id ↔ recipe_clusters.representative_recipe_id`
forms a cycle in the FK graph. After a local `cluster` run, both sides of
the cycle land in the dirty set referencing each other. With NOT
DEFERRABLE FKs, an UPSERT batched across both tables cannot satisfy
constraints in any single statement order. Making just those two FKs
`DEFERRABLE INITIALLY IMMEDIATE` lets the uploader issue
`SET CONSTRAINTS ALL DEFERRED` inside its transaction — constraints are
then checked at COMMIT for these two FKs only, breaking the ordering
problem. `INITIALLY IMMEDIATE` keeps default semantics for every other
write path; only the uploader's explicit `SET CONSTRAINTS` changes
behavior, and `SET CONSTRAINTS ALL DEFERRED` is a no-op on FKs that are
not deferrable, so the broader schema is unaffected.

**Scope.** A single migration that uses `ALTER TABLE ... ALTER CONSTRAINT
... DEFERRABLE INITIALLY IMMEDIATE` on exactly two named constraints:

- `recipes_cluster_id_fkey` (on `public.recipes`)
- `recipe_clusters_representative_recipe_id_fkey` (on `public.recipe_clusters`)

`ALTER CONSTRAINT` is metadata-only — no row is touched, no validation
re-pass is needed, no FK protection is dropped at any moment. The
migration also includes a verification step that asserts both constraints
ended in the expected `condeferrable = true / condeferred = false` state.

**Why named-and-targeted instead of generic-over-information_schema.**
Two reasons. (1) Smallest blast radius: only the FKs we actually need
become deferrable; everything else stays exactly as-is. (2) Better
auditability: anyone reading the schema can see "these two FKs are
deferrable, both because of the recipes/cluster cycle" instead of a
schema-wide property they have to reason about. The cost of remembering
to make a future cycle's FKs deferrable is small — when a future cycle
is added, the uploader will fail loudly on its first run with an FK
error pointing at the exact constraint, and the fix is one ALTER in
that cycle's own migration.

**Where it lands.** Its own PR, merged to `main` and promoted to `staging`
before the uploader PR lands. Both pre-work migrations must be applied to
staging before the uploader's smoke tests can exercise the
SET-CONSTRAINTS-DEFERRED path against staging.

## Owned tables (in upsert order)

Nine tables in the `public` schema. Order is the natural FK dependency
order; with deferrable constraints the order is mostly cosmetic but we
keep it predictable for log readability.

| # | Table | PK | Sequence | FKs out |
|---|---|---|---|---|
| 1 | `recipes` | `id` (bigserial) | `recipes_id_seq` | `cluster_id → recipe_clusters` |
| 2 | `taxonomy_nodes` | `id` (bigserial) | `taxonomy_nodes_id_seq` | — |
| 3 | `cocktail_aliases` | `(alias, canonical_name)` | — | — |
| 4 | `recipe_ingredients` | `id` (bigserial) | `recipe_ingredients_id_seq` | `recipe_id → recipes` |
| 5 | `taxonomy_edges` | `(parent_id, child_id)` | — | both → `taxonomy_nodes` |
| 6 | `taxonomy_aliases` | `(alias, node_id)` | — | → `taxonomy_nodes` |
| 7 | `taxonomy_provenance` | `node_id` | — | → `taxonomy_nodes` |
| 8 | `taxonomy_proposals` | `id` (bigserial) | `taxonomy_proposals_id_seq` | → `taxonomy_nodes` |
| 9 | `recipe_clusters` | `id` (bigserial) | `recipe_clusters_id_seq` | `representative_recipe_id → recipes` |

**Excluded.** `profiles` (not in dump; FKs to `auth.users`); all views
(`recipes_public`, `recipe_variants`, `taxonomy_public`); all
non-`public` schemas.

The list is defined as a Python data structure at the top of the
uploader script (table name, pk columns, sequence name or `None`). Stage
3 imports the same list. No reflection at runtime.

## Sidecar metadata file

### File shape

`<dump>.meta.json` written next to the `.dump` by `backup-supabase.sh`.
Mandatory — uploader refuses to run without it.

JSONC dialect: line comments (`// ...`) and block comments (`/* ... */`)
are allowed. Extension stays `.json` per project preference. The
uploader strips comments with a regex pre-pass before `json.loads`.

```jsonc
{
  "$schema": "./upload-to-staging.schema.json",

  // Captured AFTER pg_dump returns successfully.
  "taken_at": "2026-05-05T14:30:42.117Z",

  // sha256(host || ":" || dbname) of SUPABASE_STAGING_DB_URL.
  // Password and port are excluded — no secrets, hostname is enough to
  // distinguish projects (each Supabase project has a unique pooler host).
  "staging_fingerprint": "9f3c...",

  // Full applied-migration list at backup time, queried from
  // supabase_migrations.schema_migrations on staging.
  "applied_migrations": [
    "20260422120000",
    "20260424054315",
    "..."
  ],

  // For pairing the sidecar with the right .dump if filenames diverge.
  "dump_basename": "spiritolo-staging-20260505-143022Z.dump",

  // sha256 of the dump file (catches on-disk corruption / wrong file).
  "dump_sha256": "ab12...",

  // sha256 of `pg_restore --schema-only <dump>` output. Stable across
  // pg_restore runs on the same dump (the archive's TOC is canonical).
  // Defends against "the dump file got swapped" with a different threat
  // model than dump_sha256: confirms the schema we expect is what's in
  // the archive's TOC, independent of byte-level dump integrity.
  "dump_schema_sha256": "cd34...",

  // Bumped if the file format changes incompatibly.
  "backup_script_version": 1
}
```

### JSON Schema (canonical)

Lives at `scripts/upload-to-staging.schema.json`. Used at runtime by the
uploader (via `jsonschema` lib) to validate the sidecar before any other
work. A malformed sidecar fails fast with a precise error.

The schema is the canonical contract for the sidecar format. The Python
uploader validates against it on every run via the `jsonschema` library.
The bash backup script writes sidecars from a fixed heredoc that
conforms to the schema by construction — there is no runtime
schema-validation in bash (no acceptable pure-bash JSON tool), and the
uploader's validation on first read is the guard. If a future change
adds a Python helper to the backup path, that helper should validate
before exiting.

## Backup script changes (`scripts/backup-supabase.sh`)

After the existing `pg_dump` invocation succeeds, the script additionally:

1. Captures `T = now()` from staging (one `psql -c "select now()"` call).
   Captured **after** pg_dump completes so any row updated during the
   snapshot window has `updated_at ≤ T`. Format: ISO-8601 UTC with
   millisecond precision.
2. Queries staging:
   `select version from supabase_migrations.schema_migrations order by version`.
   The full list goes in the sidecar.
3. Computes `dump_sha256 = sha256sum <dumpfile>`.
4. Computes `dump_schema_sha256 = pg_restore --schema-only <dumpfile> | sha256sum`.
5. Computes `staging_fingerprint = sha256(host || ":" || dbname)` from
   the parsed `SUPABASE_STAGING_DB_URL`.
6. Writes `<dumpfile>.meta.json` via heredoc with comments.

If any step after pg_dump fails, the script removes the `.dump` file too
(no half-paired artifacts). Existing pg_dump-failure behavior unchanged.

## GitHub Action changes (`.github/workflows/backup-staging-db.yml`)

Single change: artifact upload `path` becomes a list:

```yaml
path: |
  spiritolo-staging-*.dump
  spiritolo-staging-*.dump.meta.json
```

Both files end up in the same artifact zip.

## Uploader (`scripts/upload-to-staging.py`)

### Form factor

Single Python file with PEP 723 inline metadata. Run via:

```bash
uv run --script scripts/upload-to-staging.py --dump path/to.dump --apply
```

Inline deps (kept minimal):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "psycopg[binary]>=3.2",
#   "jsonschema>=4",
# ]
# ///
```

### CLI

```
upload-to-staging --dump <path>
                  [--local-db <url>]    (default: $SUPABASE_DB_URL)
                  [--staging-db <url>]  (default: $SUPABASE_STAGING_DB_URL)
                  [--apply]             (without: dry-run)
                  [--yes]               (skip confirmation prompt before apply)
```

Refuses to run if either DB URL is missing. Sidecar path is auto-derived
as `<dump>.meta.json`; absent or unparseable sidecar is a hard fail.

### Order of operations

Steps 1–7 always run (dry-run and apply); step 8 only on `--apply`.

1. **Load and validate sidecar** against
   `scripts/upload-to-staging.schema.json`. Fail with `jsonschema` error
   on any violation.
2. **Verify dump integrity.** sha256 of the `.dump` file equals
   `dump_sha256`; sha256 of `pg_restore --schema-only` output equals
   `dump_schema_sha256`. (Two distinct checks — see sidecar comments.)
3. **Verify staging target.** Compute fingerprint of `--staging-db` URL,
   compare to `staging_fingerprint`. Mismatch = abort.
4. **Schema check (migration-list equality).** Query
   `supabase_migrations.schema_migrations` from both `--staging-db` and
   `--local-db`. Both lists must equal `applied_migrations` from the
   sidecar exactly. Any mismatch lists the missing/extra migrations and
   aborts.
5. **Staleness check.** For each owned table on staging:
   `select max(updated_at) from <table>`. If any value is `> taken_at`,
   abort with the offending tables and timestamps.
6. **Compute dirty set.** For each owned table on local:
   `select <all columns> from <table> where updated_at > taken_at`.
   Stash the rows in memory keyed by table; `len(rows)` is the count.
7. **Print plan.** Header (dump path, T, fingerprints OK, schema OK,
   staleness OK), per-table dirty counts, total. If no `--apply`, exit
   here.
8. **Apply** (only if `--apply`):
   - If not `--yes`, prompt for confirmation and exit on anything
     other than `y` / `yes`.
   - `BEGIN ISOLATION LEVEL SERIALIZABLE`.
   - `SET CONSTRAINTS ALL DEFERRED`.
   - **Re-verify staleness** inside the txn:
     `select max(updated_at) from <table>` for each owned table; if any
     exceeds `taken_at`, raise (rolls back).
   - **UPSERT dirty rows** per table in the order in the table above:
     `INSERT INTO <table> (<cols>) VALUES (...), (...), ... ON CONFLICT (<pk_cols>) DO UPDATE SET <non-pk-col> = EXCLUDED.<non-pk-col>, ...`.
     Built with `psycopg.sql.SQL` + `psycopg.sql.Identifier` for safe
     identifier quoting; values bound as a list of tuples per row.
     Batched ~1000 rows per `cursor.execute` call.
   - **Re-sync sequences** for each `bigserial` PK:
     `SELECT setval('<seq>', GREATEST(coalesce(max(<pk>), 0), nextval('<seq>') - 1), true) FROM <table>`.
     Idempotent and cheap.
   - `COMMIT`. If the SERIALIZABLE re-verify failed or any concurrent
     write tripped serialization, Postgres aborts and we report it.
9. **Print summary.** Per-table apply counts and the total.

### Error model

Every refusal prints exactly *what* failed and *what to do next*. No
generic "validation error" messages.

| Failure | Message form | What to do |
|---|---|---|
| Sidecar missing | "Sidecar `<path>.meta.json` not found." | Re-take backup with current `backup-supabase.sh`. |
| Sidecar invalid | "Sidecar fails schema: `<jsonschema-message>`." | Inspect the file; re-take backup. |
| dump_sha256 mismatch | "Dump file sha256 differs from sidecar." | The `.dump` was modified or wrong file. |
| Fingerprint mismatch | "Sidecar's staging fingerprint doesn't match `--staging-db`." | Confirm you're pointing at the right project. |
| Migration mismatch | "Staging has migrations the dump doesn't: A, B." | Re-take backup; or re-deploy migrations to align. |
| Staleness | "Staging table `<t>` was modified at `<ts>` > T=`<T>`." | Someone wrote to staging during the work session. Manual reconciliation required: re-take backup and re-do work. |
| Serialization conflict at COMMIT | Postgres' native error, surfaced unchanged. | Re-run `--apply`; if it persists, re-take backup. |

## Smoke tests

Live at `scripts/tests/test_upload_to_staging.py`. Pytest, integration
style. Gated on `TEST_DB_URL`; skips cleanly when unset. Same pattern as
the existing `ingredients/tests/test_db.py`.

### Fixture

Two ephemeral databases on the local Postgres at the same host as
`TEST_DB_URL`:

- `<test_db_base>_upload_local` — plays "local"
- `<test_db_base>_upload_staging` — plays "staging"

Both auto-created by the fixture if missing, all `supabase/migrations/*.sql`
applied via `psql` in alphabetical order, then identical fixture data
inserted (a small set of recipes, taxonomy nodes, ingredients, plus one
recipe-cluster cycle to exercise the deferrable-FK path).

### Scenarios

**Happy path.**
1. `pg_dump` the staging mirror to a temp file; backup-script logic
   writes the matching `.meta.json`.
2. Modify a row in the local mirror — bump a recipe's `name`. Trigger
   updates `updated_at`.
3. Run the uploader with `--apply --yes` against the two mirrors.
4. Assert: row landed on the staging mirror with the new value;
   `updated_at` carried over; sequences synced; no FK violations; exit 0.

**Staleness abort.**
1. Same setup as happy path.
2. After taking the dump, modify a row directly on the staging mirror
   (simulating a curation-UI edit during the work session). Trigger
   updates `updated_at`.
3. Modify a different row on the local mirror.
4. Run uploader. Assert: aborts at staleness step; staging row unchanged;
   exit non-zero with a message naming the staging table.

The `pg_dump` and metadata generation in the test fixture exercise the
real `backup-supabase.sh` path (we shell out to the real script against
the staging mirror), so the smoke tests cover both sides of the workflow.

### Out of scope for smoke tests

- Migration-list mismatch scenario. Hard to construct without a second
  migrations folder; covered by unit-level test of the comparison
  function (small parametrized test).
- Fingerprint mismatch. Trivially covered by unit test (give it a
  different sidecar; assert it refuses).
- dump_sha256 / dump_schema_sha256 corruption. Unit test: tamper with
  one byte of a fixture dump, expect refusal.

## Documentation deliverables

- **`docs/upload.md`** — end-to-end backup → restore → edit → upload
  flow with concrete commands. Stand-alone doc, linked from
  `docs/backups.md` and from `CLAUDE.md`.
- **`docs/backups.md`** — short cross-reference: "after restore, edits
  push back to staging via the uploader; see docs/upload.md."
- **`CLAUDE.md`** — new "Upload-to-staging" section near "Data flow"
  with the canonical command line and pointers.
- **`scripts/upload-to-staging.schema.json`** — the JSON Schema itself
  is canonical documentation of the sidecar format.

## Out of scope (deferred to Stage 3)

Wiring pipelines for the new flow — pipelines already work against
whatever `SUPABASE_DB_URL` points at, so Stage 3 is documentation +
optional safety nets, no code path changes for the pipelines themselves.

## PR plan

Two PRs, in order. Each updates `WORKFLOW_PLAN.md` to mark its work
shipped.

### PR A — Deferrable FKs migration

**Branch.** `claude/deferrable-fks-<id>` (whatever ID this session uses).

**Contents.**
- `supabase/migrations/<ts>_deferrable_public_fks.sql` — DO block looping
  over `information_schema.table_constraints` for `FOREIGN KEY`s in
  `public`, dropping and re-adding each as `DEFERRABLE INITIALLY IMMEDIATE`.
- `WORKFLOW_PLAN.md` — note the new pre-work migration alongside the
  `updated_at` one; mark `updated_at` as shipped (the existing entry is
  out of date).

**Smoke verification.** Apply to local; spot-check
`information_schema.referential_constraints.is_deferrable = 'YES'` and
`initially_deferred = 'NO'` for the public-schema FKs.

**After merge.** `git checkout staging && git merge --ff-only main && git push`
to deploy via the existing `deploy-migrations.yml` workflow.

### PR B — Sidecar / backup script / uploader / docs / smoke tests

**Branch.** `claude/upload-to-staging-<id>`.

**Depends on.** PR A merged AND deployed to staging.

**Contents.**
- `scripts/upload-to-staging.schema.json` — JSON Schema for the sidecar.
- `scripts/backup-supabase.sh` — sidecar-writing changes.
- `scripts/upload-to-staging.py` — the uploader (PEP 723 single-file).
- `scripts/tests/test_upload_to_staging.py` — smoke tests + a couple of
  unit tests for the comparison helpers.
- `.github/workflows/backup-staging-db.yml` — artifact upload glob
  expanded to include the sidecar.
- `docs/upload.md` — workflow doc.
- `docs/backups.md` — cross-reference paragraph.
- `CLAUDE.md` — new section.
- `WORKFLOW_PLAN.md` — mark Stage 2 shipped.

## Risks and mitigations

- **Backup script grows from ~50 to ~120 lines of bash.** Bash is fine
  for the additions (sha256sum, psql, heredoc); we don't reach for
  Python. Tradeoff accepted.
- **Sidecar drifts from schema.** The uploader's runtime validation
  prevents bad sidecars from being acted on. A separate test loads a
  fixture sidecar and validates against the schema, so schema edits
  that break compatibility get caught in CI.
- **JSONC parsing.** Naive regex strip of `//` and `/* */` is sufficient
  for the comments we'll write; we won't have comments inside string
  literals (no need for them).
- **PEP 723 + uv adoption.** `uv run --script` is supported in current
  uv; the rest of the project uses uv. No risk.
- **A′ migration uses `ALTER CONSTRAINT`.** Metadata-only, no row is
  touched, no FK protection is dropped. Idempotent — running the
  migration a second time leaves the constraints in the same already-
  deferrable state. The post-ALTER verification step asserts both
  constraints are `condeferrable = true / condeferred = false`; if a
  constraint name diverges from the expected default in some future
  schema, the migration fails loudly rather than silently no-op'ing.

## Success criteria

- A backup taken with the new script produces a `.dump` and a `.meta.json`
  in the same directory; the existing `pg_restore` recipe still works
  unchanged on the `.dump`.
- The GH-Action artifact for a manual workflow run contains both files.
- Running the uploader against an unmodified staging restores cleanly:
  no rows pushed, exit 0.
- Modifying a row locally and re-running with `--apply` lands the row on
  staging.
- Editing staging out-of-band during a work session causes the uploader
  to abort at the staleness step.
- Smoke tests pass in CI when `TEST_DB_URL` is set.
