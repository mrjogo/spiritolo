# Pushing local edits back to staging

End-to-end "back up staging → restore locally → run pipelines on local
→ push the diff back" workflow. Implements the model laid out in
[WORKFLOW_PLAN.md] (which gets deleted once Stage 3 ships).

## When to use this

You want to run a Supabase-writing pipeline (parser, mapper Phase 2,
normalize-names, cluster, …) without hitting staging directly — for
speed, for free-tier egress, or because you're iterating and may want
to throw the result away. The protected push at the end means an honest
mistake doesn't clobber the curation UI's edits.

You **don't** need this for read-only work, schema migrations (those
flow through `git push` to the `staging` branch and the
deploy-migrations workflow), or one-off SQL hand-edits to staging.

## The four steps

### 1. Take a backup

```bash
set -a && source /workspaces/spiritolo/.env && set +a
cd ~/somewhere-outside-the-repo
/workspaces/spiritolo/scripts/backup-supabase.sh
```

Produces two files:
```
spiritolo-staging-<UTC>.dump
spiritolo-staging-<UTC>.dump.meta.json
```

The sidecar carries the snapshot timestamp `T`, the staging URL
fingerprint, the applied-migration list, and integrity hashes. The
uploader requires both files. See
[scripts/src/upload_to_staging/sidecar.schema.json] for the schema.

### 2. Restore into local Supabase

Standard restore (same as before, only the .dump matters here):

```bash
# On Mac host:
supabase db reset --yes

# From devcontainer:
pg_restore \
  --dbname="$SUPABASE_DB_URL" \
  --clean --if-exists --no-owner --no-privileges \
  --single-transaction \
  ~/path/to/spiritolo-staging-*.dump
```

### 3. Run pipelines locally

Point pipelines at local (the default for `SUPABASE_DB_URL`) and run
freely. Borked the local DB? Re-restore the dump.

```bash
cd ingredients && uv run python -m ingredients.cli           # parser
cd ingredients && uv run python -m ingredients.cli map       # mapper Phase 1
# ... etc.
```

### 4. Push the diff back

```bash
cd /workspaces/spiritolo
uv run --package spiritolo-scripts python -m upload_to_staging \
  --dump ~/path/to/spiritolo-staging-<UTC>.dump
```

Without `--apply` the script prints a per-table dirty-row count and
exits. Add `--apply` to actually push:

```bash
uv run --package spiritolo-scripts python -m upload_to_staging \
  --dump ~/path/to/spiritolo-staging-<UTC>.dump \
  --apply
```

(`--yes` skips the y/N prompt.)

## What the uploader checks

In order, before any write:

1. Sidecar present and validates against the schema.
2. Dump file's sha256 matches sidecar (catches wrong file / corruption).
3. Dump's schema-only sha256 matches sidecar (catches archive
   tampering).
4. Staging URL's `host:dbname` fingerprint matches sidecar (catches
   pointing at the wrong project).
5. `supabase_migrations.schema_migrations` lists match exactly between
   the sidecar, local, and staging (catches a migration landing during
   the work session).
6. `max(updated_at)` on every owned staging table is `<= taken_at`
   (catches staging writes during the work session).

Any failure aborts with a precise message.

On `--apply`, the push runs inside a SERIALIZABLE transaction with
`SET CONSTRAINTS ALL DEFERRED`, re-verifies staleness, UPSERTs every
dirty row, resyncs sequences for the bigserial-PK tables, and commits.

## Honor system

The whole workflow assumes a single human writer (you). The staleness
check defends against accidental concurrent writes, but it can't help
if you ignore it: don't make a curation-UI edit to staging mid work
session, and if you do, re-take the backup before doing more work.

## When the uploader refuses

| Message starts with | What it means | What to do |
|---|---|---|
| `Sidecar not found` | The .meta.json is missing next to the dump | Re-take backup — older dumps predate this workflow. |
| `Dump file sha256 differs` | The .dump file isn't the one the sidecar describes | You probably grabbed the wrong file. |
| `Dump schema-only sha256 differs` | The dump's schema-only output doesn't match the sidecar (archive corruption or tampering) | Re-take backup. |
| `Sidecar's staging fingerprint doesn't match` | --staging-db points at a different project than the dump | Confirm the URL. |
| `Migration list mismatch` | A migration ran on staging since the backup | Re-take backup. |
| `Staging was modified` | Someone wrote to staging after the backup | Re-take backup, redo work. |
| `Staging changed between the pre-check and the apply txn` | A concurrent staging write landed during the brief read-then-write window | Re-run; if it persists, re-take backup. |
| `Serialization conflict at COMMIT` | A concurrent staging write tripped SERIALIZABLE | Re-run --apply; if it persists, re-take backup. |

[WORKFLOW_PLAN.md]: ../WORKFLOW_PLAN.md
[scripts/src/upload_to_staging/sidecar.schema.json]: ../scripts/src/upload_to_staging/sidecar.schema.json
