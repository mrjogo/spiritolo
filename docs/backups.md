# Database backups

The live database is one SQLite file, `/data/spiritolo.db`, on the Railway
volume. Two layers protect it:

1. **Litestream, continuous.** The entrypoint runs the app as a child of
   `litestream replicate`, which ships every WAL segment to the Litestream
   bucket (`s3://$LITESTREAM_BUCKET/spiritolo`) within about a second, keeps 7 days of
   WAL history and takes a full snapshot daily ([`litestream.yml`](../litestream.yml)).
   Point-in-time restore to any moment in that window.
2. **`VACUUM INTO` snapshots, operator-driven.** A compact, self-contained copy
   of the file you can keep anywhere (`scripts/snapshot-sqlite.sh`). Useful
   before a risky run or an import, and as the "cold copy" outside the bucket.

## Restore from Litestream

**Fresh volume (automatic).** If the service starts and `/data/spiritolo.db` is
missing, the entrypoint runs `litestream restore -if-replica-exists` first, so
replacing a volume or moving the service is just a redeploy.

**Point in time (manual).** From any machine with the Litestream binary and
the bucket credentials in the environment:

```bash
export LITESTREAM_ACCESS_KEY_ID=… LITESTREAM_SECRET_ACCESS_KEY=…   # from the vault, in a shell you'll close
litestream restore -o ./restored.db \
  -timestamp 2026-10-22T18:00:00Z \
  -endpoint "$LITESTREAM_ENDPOINT" \
  "s3://$LITESTREAM_BUCKET/spiritolo"
```

Then load `restored.db` through **/ops → Import** (stage, verify, apply); the
service restarts and comes back on that file. Litestream starts a new
generation for the replaced database automatically.

## `VACUUM INTO` snapshot

```bash
scripts/snapshot-sqlite.sh /data/spiritolo.db /data/snapshots/spiritolo-$(date -u +%Y%m%dT%H%M%SZ).db
```

Runs `VACUUM INTO` through Python's `sqlite3`, which is safe against a live WAL
database (readers and the writer keep going). Run it from a Railway shell
(`railway ssh`) or locally against a restored copy. Snapshots are plain SQLite
files: inspect them with `sqlite3`, or import one through `/ops → Import`.

## Inspect any copy

```bash
sqlite3 spiritolo.db 'pragma integrity_check; select filename from schema_migrations;'
sqlite3 spiritolo.db 'select count(*) from recipes; select count(*) from audit_log;'
```

## The legacy Postgres dump

`scripts/backup-supabase.sh` and the *Backup staging database* GitHub Action
dumped the old Supabase Postgres (`public` + `audit` schemas, custom format)
for the one-time migration ([migration.md](migration.md)). Both were removed
once it was done; they live on in git history.
