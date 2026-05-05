#!/usr/bin/env bash
# Restore a staging dump into the local Supabase Postgres.
#
# Usage: scripts/restore-local.sh <dump-file>
#
# Workaround: `public.profiles` is excluded from staging dumps, but the
# local migration creates a `set_updated_at` trigger on it that depends
# on `public.set_updated_at()`. The dump's `--clean` step DROPs that
# function and fails on the dependency. Drop the trigger first, restore,
# then recreate it.
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

restore_trigger() {
  psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
    drop trigger if exists set_updated_at on public.profiles;
    create trigger set_updated_at
      before update on public.profiles
      for each row execute function public.set_updated_at();
  " >/dev/null
}
trap restore_trigger EXIT

psql "$DB_URL" -v ON_ERROR_STOP=1 -c \
  "drop trigger if exists set_updated_at on public.profiles;" >/dev/null

pg_restore \
  --dbname="$DB_URL" \
  --clean --if-exists \
  --no-owner --no-privileges \
  --single-transaction \
  "$DUMP"
