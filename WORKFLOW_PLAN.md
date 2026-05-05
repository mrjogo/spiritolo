# Local-edit / staging-upload workflow rollout

Outer roadmap for moving spiritolo to a backup-restore-edit-upload model. Each
stage is its own AI session and PR. **Delete this file once all stages have
shipped.**

**Each stage's session must mark its stage shipped in this file (an italic
status note next to the heading) as part of its PR — before opening it.**

## The target workflow

1. Run `scripts/backup-supabase.sh` — produces a `pg_dump` custom-format dump
   of staging's `public` schema (already exists; see [docs/backups.md]).
2. Restore the dump into local Supabase (already documented).
3. Point pipelines at local (`SUPABASE_DB_URL` = local) and run them
   freely. Borked the local DB? Re-restore the dump.
4. Run a new uploader script: `scripts/upload-to-staging.sh --dump <file>
   --local-db <url> --staging-db <url>`. The uploader holds **all** the
   protections — staleness check, schema/fingerprint match, dry-run by
   default, SERIALIZABLE push.

Background context for sessions: staging is the source of truth for
`recipes`, `recipe_ingredients`, `recipe_clusters`, taxonomy growth, etc.
Bulk pipeline runs happen locally for speed and free-tier egress. The
curation UI on staging must not be silently clobbered. Single writer (just
me); honor system on "don't edit staging during a work session" is fine.

---

## Pre-work — `updated_at` migration *(shipped)*

**Goal.** Add an auto-maintained `updated_at TIMESTAMPTZ` column to every
public-schema table. Required so the uploader can compute the dirty set as
"rows in local where `updated_at > <dump timestamp>`."

---

## Pre-work — Deferrable public-schema FKs

**Goal.** Make every `FOREIGN KEY` in the `public` schema
`DEFERRABLE INITIALLY IMMEDIATE` so the uploader can issue
`SET CONSTRAINTS ALL DEFERRED` inside its serializable transaction. Without
this, the cycle between `recipes.cluster_id` and
`recipe_clusters.representative_recipe_id` blocks any UPSERT batch that
touches both sides — and any future cycle would block the same way.

**Scope.** One migration that loops over `information_schema.table_constraints`
for `FOREIGN KEY`s in `public`, drops each, re-adds it as
`DEFERRABLE INITIALLY IMMEDIATE`. `INITIALLY IMMEDIATE` keeps default
behavior for normal queries unchanged.

**Blocks.** Stage 2's `--apply` path. Smoke tests for Stage 2 cannot exercise
the deferred-constraint path against staging until this is deployed there.

**Lands as.** Its own PR (`claude/stage2-uploader-prework`), promoted to
staging via the standard `main → staging` flow before Stage 2's PR lands.

See [docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md](docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md)
for the full Stage 2 design and the role of this migration in it.

---

## Stage 1 — Remove all seed files *(shipped — PR #51)*

**Goal.** Delete every file under `supabase/seeds/`. Reference data
(taxonomy, cocktail aliases, dev admin) now flows local ← staging via backup
restore — there is no separate "seed locally" path anymore.

**Scope.**
- Delete every `*.sql` under `supabase/seeds/`:
  - `recipes.sql` (frozen historical pg_dump)
  - `taxonomy_nodes_*.sql` (all family files)
  - `cocktail_aliases.sql`
  - `dev_admin_user.local-only.sql`
- Audit `supabase/config.toml` `[db.seed]` and remove or empty
  `sql_paths`; nothing should reference removed files.
- Search for utilities or scripts that load any of these files (`git grep
  supabase/seeds`); remove or update them. Update any `Makefile` /
  convenience scripts.
- Update `docs/pipeline.md` and the relevant sections of `CLAUDE.md`:
  - Remove the "edit `supabase/seeds/taxonomy_nodes.sql` and re-run
    `supabase db reset`" workflow for adding taxonomy nodes.
  - Replace with: taxonomy nodes are now managed via the curation UI on
    staging; local devs pull a fresh backup and restore to get current
    reference data.
  - Remove references to `recipes.sql` restore.
  - Note that local admin access requires re-inviting via Studio after
    restore (already documented in `docs/backups.md`).
- Do NOT modify historical plan/spec docs under `docs/superpowers/`.

**Out of scope.** Anything about the uploader.

**Deliverables.**
- One PR. After merge: `supabase/seeds/` is empty or gone; `git grep
  'supabase/seeds'` returns nothing actionable; `docs/pipeline.md` and
  `CLAUDE.md` describe the backup-restore flow as the only path to populate
  local.

---

## Stage 2 — Build the uploader script

**Goal.** Implement `scripts/upload-to-staging.sh` (or `.py` — session
chooses). All protections live here.

**Depends on.** Pre-work migration applied to staging.

**Required CLI shape.**

```
upload-to-staging --dump <path> --local-db <url> --staging-db <url> [--apply]
```

**Required protections (in order):**

1. **Read the dump's authoritative timestamp.** Parse `pg_restore --list
   <dump>` for the archive-creation timestamp (the TOC header has it).
   This is the snapshot reference time `T`. Don't trust the filename.
2. **Staging DB fingerprint check.** Hash `(host, dbname)` of `--staging-db`;
   refuse if it doesn't match the staging URL the dump was taken from.
   Store the fingerprint in the dump's TOC if needed (the backup script can
   be tweaked to label the dump). If that's awkward, accept a
   `--expected-fingerprint` flag and fail loudly if not provided.
3. **Schema version check.** Compare the latest applied migration on staging
   against the dump's recorded schema. The dump preserves migration table
   contents — read it. Hardfail on mismatch (means a migration landed during
   the work session).
4. **Staleness check.** Per owned table, query `max(updated_at)` on staging.
   Hardfail if any table's value is `> T`. That means staging was written to
   during the work session — manual reconciliation required.
5. **Compute the dirty set.** Per owned table, query the local DB for rows
   where `updated_at > T`. Print a per-table count summary.
6. **Dry-run by default.** Without `--apply`, print the summary and exit. With
   `--apply`:

   ```sql
   BEGIN ISOLATION LEVEL SERIALIZABLE;
     -- re-verify max(updated_at) per table matches step 4 result
     -- UPSERT all dirty rows
   COMMIT;
   ```

   If the SERIALIZABLE check fails (someone wrote to staging between step 4
   and the COMMIT), Postgres rejects the commit and the script aborts. No
   partial writes.

**Owned-tables list.** Defined once in the script (or in a small Python
helper module imported by the script). Stage 3 reads from this list.

**Out of scope.**
- Wiring pipelines into anything new (Stage 3).
- Trigger-based dirty tracking. The timestamp diff is sufficient because no
  current pipeline deletes; manual deletes during a work session are
  forbidden by convention and called out in the docs.
- Multi-machine / multi-writer coordination.
- Automated reconciliation on staleness conflict — manual is fine.

**Deliverables.**
- One PR with the uploader script.
- New section in `docs/backups.md` (or new `docs/upload.md`) covering the
  full backup-restore-edit-upload flow end to end with concrete commands.
- New section in `CLAUDE.md` describing the workflow.
- Smoke tests: (a) modify a row locally, run uploader against a clean
  staging mirror, verify the row landed; (b) modify staging out-of-band
  during a "work session," attempt upload, verify staleness hardfail.

---

## Stage 3 — Sweep the pipelines

**Goal.** Each Supabase-writing pipeline gets its docs and any obvious safety
net updated for the new workflow. **No structural code changes** — the
pipelines already work against whatever DB `SUPABASE_DB_URL` points at; the
new workflow just changes which DB that is.

**Depends on.** Stage 2.

**Per-utility PR scope.** For each pipeline, the session should:
- Re-read the utility and confirm it has no hardcoded staging connection.
- Update its section in `docs/pipeline.md` and `CLAUDE.md` to describe the
  new flow (point at local, run, then run uploader). Drop any references
  to seed files or local-as-truth language.
- Optionally add a startup check that warns (not refuses) if
  `SUPABASE_DB_URL` looks like a Supabase pooler hostname, with a
  one-line "did you mean to write directly to staging?" prompt or log.
  Skip if it adds friction without value — judgement call.
- Verify with the utility's existing `--review` mode that nothing regressed.

**Sub-PRs.**

- 3a. **`scraper/src/extract.py` + `ingredients.cli` parser** —
  extract writes `recipes`; parser (default `ingredients.cli` command)
  writes `recipe_ingredients`. Grouped because they're the two foundational
  ingest steps and naturally run as a pair.
- 3b. **All `ingredients.cli map`** — Phase 1 (`map`), Phase 2
  (`map resolve-pending`, LLM cost), and `map review-proposals`.
- 3c. **All `ingredients.cli normalize-names`** — Phase 1
  (`normalize-names`) and Phase 2 (`normalize-names resolve-pending`,
  LLM cost).
- 3d. **`ingredients.cli cluster` + `ingredients.cli promote-substances`** —
  cluster compute and the post-D substance-promotion one-shot.

**Out of scope.** Behavior changes. Version-constant bumps. Lease-awareness
(there is no lease).

**Deliverables.** One PR per sub-stage on `claude/upload-<utility>-<id>`
branches.

---

## Cleanup

After Stage 3 sub-PRs all ship and the workflow has been exercised on at
least one real edit cycle: delete `WORKFLOW_PLAN.md`.

[docs/backups.md]: docs/backups.md
