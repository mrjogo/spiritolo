# Database backups

`pg_dump` of the staging Supabase `public` schema, plus a `pg_restore`-based
recovery flow. Triggered manually or via the `Backup staging database`
GitHub Action.

## What's in the dump, what isn't

**In:** every table, view, function, sequence, index, and constraint in the
`public` schema and their data. Format is `pg_dump --format=custom` — a
binary archive with internal gzip compression. Read it with `pg_restore`.

**Excluded — `public.profiles`.** Rows there FK to `auth.users(id)`, and
the `auth` schema is Supabase-managed and not in our dump. On restore,
admins re-invite themselves from Studio, the `handle_new_user` trigger
writes a fresh `profiles` row on first sign-in, and we flip `is_admin =
true` from the table editor.

**Excluded — `auth` / `storage` / `realtime` / `vault` / `extensions`.**
Platform-managed; not our data.

If a future `public` table FKs to `auth.users`, either exclude it the
same way or denormalize an `email` column onto it as a recovery anchor.

> **Pushing edits back to staging?** After restoring a backup locally,
> running pipelines, and wanting to upload the diff, see
> [docs/upload.md](upload.md). The backup script writes a sidecar
> metadata file alongside the .dump that the uploader requires.

## Run a backup

**Manual:**

```bash
set -a && source /workspaces/spiritolo/.env && set +a
cd ~/somewhere-outside-the-repo                       # default dest is cwd
/workspaces/spiritolo/scripts/backup-supabase.sh      # → spiritolo-staging-<UTC>.dump
/workspaces/spiritolo/scripts/backup-supabase.sh --label before-migration
```

`SUPABASE_STAGING_DB_URL` must be the **Supavisor session pooler**
(`aws-0-<region>.pooler.supabase.com:5432`). The script refuses the
IPv6-only direct connection and the transaction pooler (port 6543).

**GitHub Action:** Actions tab → "Backup staging database" → Run workflow.
The dump is uploaded as a 7-day workflow artifact named
`spiritolo-staging-dump-<run-id>`. Don't enable the cron schedule until
durable storage (B2/R2/S3) is wired up — GHA's 500 MB free-tier artifact
quota fills fast.

## Inspect a dump (no DB required)

```bash
file path/to/dump.file
# → "PostgreSQL custom database dump - v1.16-0"

pg_restore --list path/to/dump.file | less
# → header (server version, dump version, timestamp) + TOC of every object
```

## Restore

You need `pg_restore` whose major version is ≥ the dump's server (currently
17). Devcontainer ships with 17 already. Install snippet for fresh hosts at
the bottom of this doc.

### Recover dev data into local Supabase

The "I want realistic data locally" flow. Local Supabase keeps its
migration-applied schema; the dump replaces the data.

```bash
# On Mac host:
supabase db reset --yes      # migrations replay → empty public, populated auth

# From devcontainer:
pg_restore \
  --dbname="$SUPABASE_DB_URL" \
  --clean --if-exists \
  --no-owner --no-privileges \
  --single-transaction \
  path/to/spiritolo-staging-*.dump
```

`--clean --if-exists` issues `DROP ... IF EXISTS` before each CREATE,
replacing the migration-created public objects with the dump's versions.
`--single-transaction` rolls everything back if any object fails — strongly
recommended; an aborted half-restore is messier than starting over.

`profiles` is left alone (excluded from the dump). To get an admin
account locally, sign in as your dev user → `handle_new_user` creates
the row → set `profiles.is_admin = true` via Studio or `psql`.

### Disaster recovery — fresh Supabase project

```bash
# 1. Create new Supabase project. Capture its session-pooler URL as $NEW_DB_URL.

# 2. Apply migrations.
supabase db push --db-url "$NEW_DB_URL" --include-all

# 3. Restore data.
pg_restore \
  --dbname="$NEW_DB_URL" \
  --clean --if-exists \
  --no-owner --no-privileges \
  --single-transaction \
  spiritolo-staging-*.dump

# 4. Re-invite admins from Studio (Auth → Users → Invite). On first sign-in
#    the handle_new_user trigger writes their profiles row; flip is_admin
#    from the table editor.

# 5. Update SUPABASE_STAGING_DB_URL repo secret + Vercel env var to point
#    at the new project, then re-deploy.
```

### Data-only restore (one table)

```bash
pg_restore \
  --dbname="$TARGET_URL" \
  --data-only \
  --table=recipes \
  --single-transaction \
  spiritolo-staging-*.dump
```

`--data-only` skips DDL — target's `recipes` must already exist with
matching column structure.

### Spelunking — restore into a sandbox DB for querying

```bash
createdb -h host.docker.internal -U postgres dump_inspect
pg_restore \
  --dbname=postgresql://postgres:postgres@host.docker.internal:54322/dump_inspect \
  --no-owner --no-privileges \
  spiritolo-staging-*.dump
psql -h host.docker.internal -U postgres -d dump_inspect
# ... when done:
dropdb -h host.docker.internal -U postgres dump_inspect
```

## Verifying schema compatibility before a restore

If you're worried the target's `public` schema has drifted from the
dump's, diff with `migra`:

```bash
uv tool install migra --with psycopg2-binary

createdb -h host.docker.internal -U postgres dump_compare
pg_restore --schema-only --no-owner --no-privileges \
  --dbname=postgresql://postgres:postgres@host.docker.internal:54322/dump_compare \
  spiritolo-staging-*.dump
migra "$TARGET_URL" \
  postgresql://postgres:postgres@host.docker.internal:54322/dump_compare \
  --schema public --unsafe
dropdb -h host.docker.internal -U postgres dump_compare
```

Empty output = schemas match. Any output is the SQL diff to make
`$TARGET_URL` match the dump.

For `--clean --if-exists` restores, schema drift is mostly harmless (the
dump's DDL replaces the target's anyway), but the diff tells you what's
about to change.

## Installing pg_dump / pg_restore on a fresh host

The devcontainer has 17 already. On a fresh Linux box:

```bash
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list > /dev/null
sudo apt-get update
sudo apt-get install -y postgresql-client-17
pg_dump --version    # → pg_dump (PostgreSQL) 17.x
```

On macOS: `brew install postgresql@17`.
