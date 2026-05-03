#!/usr/bin/env bash
# scripts/upload-data-to-staging.sh
#
# One-time bootstrap: mirror local application data to the
# spiritolo-staging Supabase project. Excludes auth.* and profiles —
# staging manages its own user accounts, and we never want the local
# dev admin (admin@local.test) to leak there.
#
# Idempotent: truncates the application tables on staging before
# loading, so re-running gives a clean mirror rather than appending
# duplicates.
#
# Usage:
#   scripts/upload-data-to-staging.sh <staging-pooler-url>
#   scripts/upload-data-to-staging.sh <staging-pooler-url> --yes
#
# The staging URL must be the Session Pooler URI from the Supabase
# dashboard (postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres),
# not the IPv6-only direct-connection URL.

set -euo pipefail

if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
  exit 64
fi

STAGING_URL="$1"
ASSUME_YES="${2:-}"
LOCAL_URL="${SUPABASE_DB_URL:-postgresql://postgres:postgres@192.168.65.254:54322/postgres?sslmode=disable}"

# Application tables, in load order. recipe_clusters and recipes have a
# circular FK; we drop+recreate around the load.
TABLES=(
  taxonomy_nodes
  taxonomy_edges
  taxonomy_aliases
  taxonomy_provenance
  taxonomy_proposals
  cocktail_aliases
  recipe_clusters
  recipes
  recipe_ingredients
)

# Refuse if the staging URL looks local — defense against running
# this against the dev DB by mistake.
if [[ "$STAGING_URL" == *"192.168.65.254"* \
   || "$STAGING_URL" == *"host.docker.internal"* \
   || "$STAGING_URL" == *"localhost"* \
   || "$STAGING_URL" == *"127.0.0.1"* ]]; then
  echo "ERROR: staging URL appears to be a local address. Refusing to run." >&2
  exit 1
fi

DUMP=$(mktemp -t spiritolo-data-XXXXXX.sql)
trap "rm -f '$DUMP'" EXIT

table_args=()
truncate_list=""
for t in "${TABLES[@]}"; do
  table_args+=(--table="public.$t")
  truncate_list+="public.$t,"
done
truncate_list="${truncate_list%,}"

# Build a single counts query reused for the before/after/local
# comparisons. auth.users + profiles included as a sanity reminder
# that we are NOT touching them.
count_sql="select 'auth.users (NOT touched)' as t, count(*)::text as n from auth.users
  union all select 'profiles    (NOT touched)', count(*)::text from public.profiles"
for t in "${TABLES[@]}"; do
  count_sql+=" union all select '$t', count(*)::text from public.$t"
done

echo "=== Step 1/4: Dumping local data tables ==="
pg_dump "$LOCAL_URL" \
  --data-only \
  --no-owner \
  --no-privileges \
  "${table_args[@]}" \
  > "$DUMP"

dump_size=$(du -h "$DUMP" | cut -f1)
echo "  Dump file: $DUMP ($dump_size)"

echo
echo "Local counts:"
psql "$LOCAL_URL" -c "$count_sql"

echo
echo "=== Step 2/4: Inspecting staging current state ==="
echo "Staging counts BEFORE truncate (target tables will be wiped):"
psql "$STAGING_URL" -c "$count_sql"

if [[ "$ASSUME_YES" != "--yes" ]]; then
  echo
  read -p "Proceed with truncate + load? [y/N] " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo
echo "=== Step 3/4: Truncate + load (single transaction) ==="
# Heredoc passes the SQL to psql; \i sources the dump file as a script.
# The whole operation is wrapped in BEGIN/COMMIT so a failure rolls
# back to the pre-truncate state.
psql "$STAGING_URL" -v ON_ERROR_STOP=1 <<EOF
\set ON_ERROR_STOP on
begin;

-- Drop circular FKs so truncate-cascade doesn't trip and load
-- doesn't have to navigate the cycle.
alter table public.recipes
  drop constraint if exists recipes_cluster_id_fkey;
alter table public.recipe_clusters
  drop constraint if exists recipe_clusters_representative_recipe_id_fkey;

-- Wipe target tables. CASCADE is defensive — if a future migration
-- adds a child table not in our list, this still succeeds.
truncate table $truncate_list cascade;

-- Load the dump (COPY statements + setval for sequences).
\i $DUMP

-- Recreate the circular FKs.
alter table public.recipes
  add constraint recipes_cluster_id_fkey
  foreign key (cluster_id) references public.recipe_clusters(id);
alter table public.recipe_clusters
  add constraint recipe_clusters_representative_recipe_id_fkey
  foreign key (representative_recipe_id) references public.recipes(id);

commit;
EOF

echo
echo "=== Step 4/4: Verification ==="
echo "Staging counts AFTER load (should match local for application tables):"
psql "$STAGING_URL" -c "$count_sql"

echo
echo "Done."
