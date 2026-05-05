#!/usr/bin/env bash
# Data-only restore of a staging dump into local Supabase. Local schema
# is migration-managed; this script just refreshes the data, leaving
# `public.profiles` (excluded from the dump; FKs auth.users) untouched.
#
# Uses `session_replication_role = replica` instead of pg_restore's
# `--disable-triggers` because the latter calls ALTER TABLE DISABLE
# TRIGGER ALL, which fails on the FK constraint triggers ("system
# triggers") with the local Supabase postgres role. The session-level
# flag has the same effect (no FK / user trigger firing during the load)
# and works around the recipes ↔ recipe_clusters circular FK.
#
# Usage: scripts/restore-local.sh <dump-file>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $(basename "$0") <dump-file>" >&2
  exit 2
fi

DUMP="$1"
DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"

if [[ ! -f "$DUMP" ]]; then
  echo "Error: dump file not found: $DUMP" >&2
  exit 1
fi

# Migration check: if the sidecar is present, the local schema must be
# at the dump's migration version. Otherwise the COPYs below will likely
# fail on column mismatches anyway — better to say so up front.
SIDECAR="${DUMP}.meta.json"
if [[ -f "$SIDECAR" ]]; then
  command -v jq >/dev/null \
    || { echo "Error: jq required for sidecar migration check" >&2; exit 1; }
  EXPECTED=$(jq -r '.applied_migrations[]?' "$SIDECAR" | sort)
  LOCAL=$(psql "$DB_URL" -tAX -c \
    "select version from supabase_migrations.schema_migrations order by version" \
    2>/dev/null || true)
  if [[ "$EXPECTED" != "$LOCAL" ]]; then
    echo "Error: local migrations don't match the dump's." >&2
    diff <(echo "$EXPECTED") <(echo "$LOCAL") || true
    echo "Run 'supabase db reset --yes' (or 'supabase migration up --include-all') first." >&2
    exit 1
  fi
fi

echo "Restoring data from $DUMP..."
{
  echo "SET LOCAL session_replication_role = replica;"
  cat <<'SQL'
do $$
declare r record;
begin
  for r in
    select tablename from pg_tables
    where schemaname = 'public' and tablename <> 'profiles'
  loop
    execute format('truncate table public.%I restart identity cascade', r.tablename);
  end loop;
end$$;
SQL
  pg_restore --data-only --no-owner --no-privileges -f - "$DUMP"
} | psql "$DB_URL" -v ON_ERROR_STOP=1 --single-transaction --quiet

echo "Done."
