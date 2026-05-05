#!/usr/bin/env bash
# Back up the Supabase hosted Postgres `public` schema to a custom-format
# pg_dump. Excludes `public.profiles` — those rows FK to `auth.users`,
# which Supabase manages and we don't dump; on restore, admins re-invite
# themselves and re-flip `is_admin` from Studio.
#
# Local: source the repo .env first, then `./scripts/backup-supabase.sh`.
# CI:    set SUPABASE_STAGING_DB_URL in the workflow env.
#
# Quick restore:
#   pg_restore --clean --if-exists --no-owner --no-privileges \
#              --single-transaction --dbname="$TARGET_URL" path/to/file.dump
#
# Full backup + restore docs: docs/backups.md
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dest DIR] [--label TAG]

Dump the Supabase staging Postgres (public schema, custom format, gz=9) to a
timestamped file: <dest>/spiritolo-staging-<YYYYMMDD-HHMMSSZ>[-<label>].dump

Options:
  -d, --dest DIR    Destination folder (created if missing). Default: . (cwd)
  -l, --label TAG   Optional suffix appended to the filename (e.g. before-migration).
  -h, --help        Show this help.

Reads SUPABASE_STAGING_DB_URL from the environment. Must be the Supavisor
session-mode pooler (host: aws-0-<region>.pooler.supabase.com, port: 5432).
The free tier's direct connection (db.<ref>.supabase.co) is IPv6-only and
the transaction pooler (port 6543) breaks pg_dump.
EOF
}

DEST="."
LABEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dest)  DEST="$2"; shift 2 ;;
    -l|--label) LABEL="$2"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *)          echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${SUPABASE_STAGING_DB_URL:-}" ]]; then
  echo "Error: SUPABASE_STAGING_DB_URL is not set." >&2
  echo "Source the repo env first:  set -a && source .env && set +a" >&2
  exit 1
fi

# Connection-mode sanity checks. The connection string format is
#   postgresql://USER:PASS@HOST:PORT/DB?...
URL="$SUPABASE_STAGING_DB_URL"
HOSTPORT="${URL#*@}"           # strip scheme+credentials
HOSTPORT="${HOSTPORT%%/*}"     # strip path/query
HOST="${HOSTPORT%%:*}"
PORT="${HOSTPORT##*:}"
[[ "$PORT" == "$HOST" ]] && PORT=5432   # no explicit port

if [[ "$HOST" == db.*.supabase.co ]]; then
  cat >&2 <<EOF
Error: SUPABASE_STAGING_DB_URL points at the direct connection ($HOST).
On Supabase free tier this endpoint is IPv6-only and will fail from most
networks. Use the Supavisor session pooler instead:
  postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
EOF
  exit 1
fi

if [[ "$PORT" == "6543" ]]; then
  cat >&2 <<EOF
Error: SUPABASE_STAGING_DB_URL uses the transaction pooler (port 6543).
pg_dump requires session mode — switch the port to 5432.
EOF
  exit 1
fi

mkdir -p "$DEST"

TS=$(date -u +%Y%m%d-%H%M%SZ)
NAME="spiritolo-staging-${TS}"
[[ -n "$LABEL" ]] && NAME="${NAME}-${LABEL}"
OUT="${DEST}/${NAME}.dump"

cleanup_partial() {
  local rc=$?
  if (( rc != 0 )) && [[ -f "$OUT" && ! -f "$META" ]]; then
    rm -f "$OUT"
    echo "Removed partial dump $OUT (sidecar write failed)" >&2
  fi
}
trap cleanup_partial EXIT

echo "Backing up staging public schema → $OUT"
pg_dump \
  --dbname="$URL" \
  --schema=public \
  --exclude-table=public.profiles \
  --format=custom \
  --no-owner \
  --no-privileges \
  --compress=9 \
  --file="$OUT"

META="${OUT}.meta.json"

# Snapshot reference time T — captured AFTER pg_dump so any row updated
# during the snapshot window has updated_at <= T.
TAKEN_AT=$(psql "$URL" -tAX -c "select to_char(now() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')")

# Migration list at backup time. Used by the uploader's schema-version
# check.
MIGRATIONS_JSON=$(psql "$URL" -tAX -c "
  select json_agg(version order by version)
  from supabase_migrations.schema_migrations
")
[[ "$MIGRATIONS_JSON" == "" ]] && MIGRATIONS_JSON="[]"

# Fingerprint = sha256 of "host:dbname". No password, no port.
DBNAME="${URL##*/}"; DBNAME="${DBNAME%%\?*}"
FINGERPRINT=$(printf "%s:%s" "$HOST" "$DBNAME" | sha256sum | awk '{print $1}')

DUMP_SHA=$(sha256sum "$OUT" | awk '{print $1}')
SCHEMA_SHA=$(pg_restore --schema-only --no-owner --no-privileges "$OUT" \
             | sha256sum | awk '{print $1}')

cat > "$META" <<EOF_META
{
  "taken_at": "$TAKEN_AT",
  "staging_fingerprint": "$FINGERPRINT",
  "applied_migrations": $MIGRATIONS_JSON,
  "dump_basename": "$(basename "$OUT")",
  "dump_sha256": "$DUMP_SHA",
  "dump_schema_sha256": "$SCHEMA_SHA",
  "backup_script_version": 1
}
EOF_META

ls -lh "$OUT" "$META"
