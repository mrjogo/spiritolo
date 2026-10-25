# Data migration — Supabase Postgres → the Railway SQLite service

Moves everything the pipeline produced on staging Supabase (`recipes`,
`recipe_ingredients`, `recipe_steps`, `ingredient_resolutions`, the taxonomy,
clusters, exports, runs + `job_items`, `human_reviews`, the audit log, and the
Zone-1 `pages` table) into the new service's SQLite file. The path is
**secrets-blind**: nobody needs the Postgres password; the GitHub Action that
holds it produces a dump artifact, and everything after that is a file.

```
GitHub Action "Backup staging database"  →  spiritolo-staging-<ts>.dump (artifact, 7 days)
        ↓ download
scripts/pg_to_sqlite  <dump>  spiritolo.db     # offline, pg_restore --data-only → parse → SQLite
        ↓
/ops → Import: stage (upload + verify) → apply (service restarts on the new file)
```

## 1. Export

> Done once, on 2026-10-24. The workflow and `scripts/backup-supabase.sh` have
> since been removed; restore them from git history if a dump is ever needed
> again.

Actions tab → **Backup staging database** → *Run workflow* (pick the branch
that carries the current `scripts/backup-supabase.sh`, which dumps the `audit`
schema too). The run uploads `spiritolo-staging-dump-<run-id>` containing the
`.dump` and a `.meta.json` sidecar. It needs the `SUPABASE_STAGING_DB_URL`
repo secret to be the session-pooler URL (`postgres.<ref>@…pooler…:5432`).

## 2. Convert

Needs `pg_restore` on PATH (any major ≥ the dump's server; no Postgres
*server* is involved):

```bash
cd scripts && uv run python -m pg_to_sqlite ~/Downloads/spiritolo-staging-*.dump ../out/spiritolo.db
# → pages=N taxonomy_nodes=N recipes=N … audit_log=N skipped:public.profiles=N
```

What the ETL does (`scripts/src/pg_to_sqlite/__init__.py`):

- streams `pg_restore --data-only` and parses the `COPY … FROM stdin` blocks;
- maps every column into the SQLite schema built from
  `common/db/migrations/`: `jsonb`/`text[]` → JSON text, `bool` → 0/1,
  `timestamptz` → ISO-8601 UTC millis, numerics → REAL;
- folds retired `jobs.state` values (`awaiting_approval`/`claimed` → `queued`,
  `succeeded` → `done`) and drops the approval columns;
- copies `audit.log` → `audit_log`, keeping the diff shape;
- leaves `profiles` and `worker_status` behind (passkey operators replace
  profiles; there is no worker daemon);
- finishes with `pragma foreign_key_check`, `VACUUM`, and exits 2 if anything
  dangles or an unknown table appeared.

Sanity-check the result:

```bash
sqlite3 out/spiritolo.db 'select count(*) from recipes; select count(*) from recipe_exports; pragma integrity_check;'
```

## 3. Load

Sign in to `/ops` as an admin → **Import**:

1. **Upload and verify** the file. The browser computes its SHA-256; the
   server checks the digest, opens the file read-only, runs
   `integrity_check`, confirms the migration ledger matches this build, and
   shows row counts. Because the ETL output has no `operators`, the live
   operators and passkeys are copied into the staged file, so your session
   survives the swap. Nothing live changes yet; the file sits at
   `/data/spiritolo.db.import`.
2. **Apply**. In the container the process exits (code 3) and Railway
   restarts it; the entrypoint sees the staged file, removes the old database
   (+ `-wal`/`-shm`), renames the staged file into place, and Litestream
   starts a new generation for it. The page polls `/api/health` until the
   service is back. (Locally, with `IMPORT_RESTART` unset, the swap happens
   in-process instead.)

**Discard** removes a staged file without applying it.

## 4. Verify

```bash
curl -s https://spiritolo.com/api/recipes?page_size=1 | head -c 400
```

and in `/ops`: Recipes / Exports / Audit log browsers show the migrated rows;
Runs lists the historical runs with their items.

## 5. The HTML corpus

Pages' HTML lives in the `spiritolo-corpus` bucket and is referenced by
`pages.corpus_key`, which the ETL carries over unchanged. Either keep reading
that bucket (its credentials and endpoint/name as `CORPUS_*`
variables) or copy the objects to a bucket in the new project and point the
variables there. No re-crawl is needed.

## 6. Decommission

Once the import is verified: delete the Supabase project, the
`SUPABASE_STAGING_DB_URL` secret, the backup workflow and
`scripts/backup-supabase.sh` (all done 2026-10-24, the project paused rather
than deleted). Keep one copy of the final `.dump` cold.

---

### Legacy: `corpus_loader`

`scripts/src/corpus_loader` (`import-pages`, `load-corpus`) was the earlier
one-time move of the local scraper SQLite + `data/html/` into Postgres + the
bucket. It still targets Postgres via `SUPABASE_DB_URL` and is kept only as a
reference for a future scraper → service page import.
