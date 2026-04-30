#!/usr/bin/env bash
# scripts/refresh-processed-seeds.sh
#
# Two modes:
#   restore  — apply committed processed seeds, then run deterministic
#              recompute steps so the DB matches a from-scratch run.
#   dump     — refresh committed seed files from current DB state,
#              filtered to LLM-resolved + curator-promoted rows.
#
# This is the "rinse and repeat" pattern documented in CLAUDE.md.
# Default for all stages going forward; new stages plug in by adding
# their dump/restore steps to this script.

set -euo pipefail

DB_URL="${SUPABASE_DB_URL:-postgresql://postgres:postgres@host.docker.internal:54322/postgres}"
PROCESSED_DIR="$(git rev-parse --show-toplevel)/supabase/seeds/processed"
mkdir -p "$PROCESSED_DIR"

cmd="${1:-}"

dump_table() {
  local out="$1"
  local sql="$2"
  echo "Dumping → $out"
  psql "$DB_URL" -At -c "$sql" > "$out.tmp"
  mv "$out.tmp" "$out"
}

dump_mode() {
  # 00: taxonomy nodes auto-created or substance-promoted (provenance source != 'seed').
  dump_table "$PROCESSED_DIR/00_taxonomy_grown.sql" \
    "select format(
       'insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default, is_defining_garnish) values (%L, %L, %L, %L, %L, %L) on conflict (slug) do nothing;',
       n.slug, n.display_name, n.role, n.is_cluster_node, n.role_default, n.is_defining_garnish
     )
     from taxonomy_nodes n
     join taxonomy_provenance p on p.node_id = n.id
     where p.source in ('llm-mapper', 'e-substance-promotion')
     order by n.id"

  # Edges + aliases for those grown nodes — append to the same file.
  psql "$DB_URL" -At -c "
    select format(
      'insert into taxonomy_edges (parent_id, child_id) select %L::bigint, id from taxonomy_nodes where slug = %L on conflict do nothing;',
      e.parent_id, n.slug
    )
    from taxonomy_edges e
    join taxonomy_nodes n on n.id = e.child_id
    join taxonomy_provenance p on p.node_id = n.id
    where p.source in ('llm-mapper', 'e-substance-promotion')
    order by e.parent_id, e.child_id" >> "$PROCESSED_DIR/00_taxonomy_grown.sql"

  psql "$DB_URL" -At -c "
    select format(
      'insert into taxonomy_aliases (alias, node_id) select %L, id from taxonomy_nodes where slug = %L on conflict do nothing;',
      a.alias, n.slug
    )
    from taxonomy_aliases a
    join taxonomy_nodes n on n.id = a.node_id
    join taxonomy_provenance p on p.node_id = n.id
    where p.source in ('llm-mapper', 'e-substance-promotion')
    order by a.alias" >> "$PROCESSED_DIR/00_taxonomy_grown.sql"

  # 10: D's LLM-resolved recipe_ingredients rows.
  dump_table "$PROCESSED_DIR/10_recipe_ingredients_llm.sql" \
    "select format(
       'update recipe_ingredients set taxonomy_node_id = %L, mapper_source = %L, mapper_version = %L, mapper_at = now() where recipe_id = %L and position = %L;',
       ri.taxonomy_node_id, ri.mapper_source, ri.mapper_version, ri.recipe_id, ri.position
     )
     from recipe_ingredients ri
     where ri.mapper_source = 'llm'
     order by ri.recipe_id, ri.position"

  # 20: E's LLM-resolved recipes.canonical_name rows.
  dump_table "$PROCESSED_DIR/20_recipes_normalized.sql" \
    "select format(
       'update recipes set canonical_name = %L, canonical_name_source = %L, normalizer_version = %L, normalized_at = now() where source_url = %L;',
       r.canonical_name, r.canonical_name_source, r.normalizer_version, r.source_url
     )
     from recipes r
     where r.canonical_name_source = 'llm'
     order by r.id"

  # 30: cocktail_aliases grown by LLM (or curator manual entries).
  dump_table "$PROCESSED_DIR/30_cocktail_aliases.sql" \
    "select format(
       'insert into cocktail_aliases (alias, canonical_name, source) values (%L, %L, %L) on conflict do nothing;',
       a.alias, a.canonical_name, a.source
     )
     from cocktail_aliases a
     where a.source in ('llm', 'manual')
     order by a.alias"

  echo
  echo "Dump complete. Diff:"
  git -C "$(git rev-parse --show-toplevel)" diff --stat -- "$PROCESSED_DIR" || true
}

restore_mode() {
  echo "Applying processed seeds…"
  for f in "$PROCESSED_DIR"/*.sql; do
    [ -e "$f" ] || continue
    echo "  $f"
    psql "$DB_URL" -f "$f" >/dev/null
  done

  echo "Recomputing deterministic outputs…"
  pushd "$(git rev-parse --show-toplevel)/ingredients" >/dev/null
  uv run python -m ingredients.cli map                    # alias + lexical
  uv run python -m ingredients.cli normalize-names        # phase 1
  uv run python -m ingredients.cli cluster                # cluster + variants
  popd >/dev/null

  echo "Done. DB is fully populated."
}

case "$cmd" in
  dump)    dump_mode ;;
  restore) restore_mode ;;
  *)       echo "Usage: $0 {dump|restore}" ; exit 64 ;;
esac
