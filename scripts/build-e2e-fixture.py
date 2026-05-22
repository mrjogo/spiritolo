#!/usr/bin/env python3
"""Build supabase/seeds/e2e_proposals.fixture.sql from local Supabase.

Selects ~100 pending taxonomy_proposals (capped per parent bucket for
diversity), collects all referenced taxonomy_nodes + edges + aliases,
picks one matching recipe per proposal raw_string, and emits a single
SQL transaction that lands an e2e-ready DB state.

Usage (devcontainer):

    set -a && source /workspaces/spiritolo/.env && set +a
    uv run --with 'psycopg[binary]>=3.2' \
        python /workspaces/spiritolo/scripts/build-e2e-fixture.py

The script reads SUPABASE_DB_URL from the environment, writes to
supabase/seeds/e2e_proposals.fixture.sql, and prints a summary.

Re-run any time the source DB changes; the resulting file is intended
to be checked in and applied manually after `supabase db reset`.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "supabase" / "seeds" / "e2e_proposals.fixture.sql"

# Cap per parent bucket. Tuned so the sum across buckets is ~100.
PER_BUCKET_CAP = 5


def kebab(slug: str | None) -> str | None:
    """Replace underscores with dashes — schema enforces kebab-case slugs.

    Local staging-restored data still carries pre-cleanup snake_case slugs
    from before migration 20260510150000_slug_kebab_check.sql tightened the
    rule. The migration is applied in the sandbox we test against, so the
    fixture must emit kebab-case to satisfy the CHECK constraints on
    taxonomy_nodes.slug and taxonomy_proposals.proposed_slug.
    """
    if slug is None:
        return None
    return slug.replace("_", "-")


def sql_lit(value: Any) -> str:
    """Render a Python value as a SQL literal suitable for inlining.

    Uses psycopg's libpq quoting via psycopg.sql.Literal for correctness.
    """
    return sql.Literal(value).as_string(_DUMMY_CONN)


# Dummy connection only used for libpq-quoting Literals; never executed against.
_DUMMY_CONN: psycopg.Connection | None = None


def main() -> int:
    global _DUMMY_CONN
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        print("error: SUPABASE_DB_URL is not set", file=sys.stderr)
        return 2

    with psycopg.connect(db_url) as conn:
        _DUMMY_CONN = conn
        return _build(conn)


def _build(conn: psycopg.Connection) -> int:
    # ------------------------------------------------------------------
    # 1. Pick proposals: up to PER_BUCKET_CAP per proposed_parent_id,
    #    deterministically ordered by id.
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute(
            """
            with bucketed as (
              select *, row_number() over (partition by proposed_parent_id order by id) as rn
              from taxonomy_proposals
              where status = 'pending'
            )
            select id, raw_string, proposed_slug, proposed_display_name,
                   proposed_parent_id, candidates, mapper_version, status,
                   decided_by, decided_at, created_at
            from bucketed
            where rn <= %s
            order by id;
            """,
            (PER_BUCKET_CAP,),
        )
        proposals = cur.fetchall()
        prop_cols = [d.name for d in cur.description]
    proposal_rows = [dict(zip(prop_cols, r)) for r in proposals]
    proposal_ids = [r["id"] for r in proposal_rows]
    raw_strings = [r["raw_string"] for r in proposal_rows]
    print(f"  selected {len(proposal_rows)} proposals", file=sys.stderr)

    # ------------------------------------------------------------------
    # 2. Universe of referenced taxonomy_node ids:
    #    proposed_parent_id ∪ each candidates[].node_id.
    # ------------------------------------------------------------------
    needed_node_ids: set[int] = set()
    for r in proposal_rows:
        if r["proposed_parent_id"] is not None:
            needed_node_ids.add(r["proposed_parent_id"])
        for elem in r["candidates"] or []:
            nid = elem.get("node_id") if isinstance(elem, dict) else None
            if nid is not None:
                needed_node_ids.add(int(nid))

    # ------------------------------------------------------------------
    # 3. Pick one recipe per matching raw_string (first by recipe id).
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct on (lower(trim(ri.name)))
              ri.recipe_id, ri.name as matched_raw_string
            from recipe_ingredients ri
            where lower(trim(ri.name)) = any(%s)
            order by lower(trim(ri.name)), ri.recipe_id;
            """,
            (raw_strings,),
        )
        matched = cur.fetchall()
    recipe_ids = sorted({m[0] for m in matched})
    print(f"  picked {len(recipe_ids)} distinct recipes", file=sys.stderr)

    # ------------------------------------------------------------------
    # 4. Pull all recipe_ingredients rows for those recipes, then add
    #    any taxonomy nodes they reference to our slice (so the FK
    #    relationships are coherent).
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, recipe_id, position, raw_text, amount, amount_max, unit,
                   name, modifier, parse_status, parser_rule, parser_version,
                   parsed_at, taxonomy_node_id, mapper_source, mapper_version,
                   mapper_at, role, role_source, flag_reason
            from recipe_ingredients
            where recipe_id = any(%s)
            order by recipe_id, position;
            """,
            (recipe_ids,),
        )
        ri_rows = cur.fetchall()
        ri_cols = [d.name for d in cur.description]
    ri_dicts = [dict(zip(ri_cols, r)) for r in ri_rows]
    for r in ri_dicts:
        if r["taxonomy_node_id"] is not None:
            needed_node_ids.add(r["taxonomy_node_id"])
    print(
        f"  collected {len(ri_dicts)} recipe_ingredients across those recipes",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # 5. Fetch taxonomy_nodes for our universe.
    # ------------------------------------------------------------------
    sorted_node_ids = sorted(needed_node_ids)
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, slug, display_name, node_kind, is_cluster_node,
                   default_role, is_defining_garnish, created_at
            from taxonomy_nodes
            where id = any(%s)
            order by id;
            """,
            (sorted_node_ids,),
        )
        node_rows = cur.fetchall()
        node_cols = [d.name for d in cur.description]
    node_dicts = [dict(zip(node_cols, r)) for r in node_rows]
    if len(node_dicts) != len(sorted_node_ids):
        missing = sorted(set(sorted_node_ids) - {n["id"] for n in node_dicts})
        raise RuntimeError(f"missing taxonomy_nodes for ids: {missing}")
    print(f"  collected {len(node_dicts)} taxonomy_nodes", file=sys.stderr)

    # ------------------------------------------------------------------
    # 6. Taxonomy edges/aliases that fall entirely inside our slice.
    # ------------------------------------------------------------------
    node_id_set = {n["id"] for n in node_dicts}
    with conn.cursor() as cur:
        cur.execute(
            """
            select parent_id, child_id, created_at
            from taxonomy_edges
            where parent_id = any(%s) and child_id = any(%s)
            order by parent_id, child_id;
            """,
            (sorted_node_ids, sorted_node_ids),
        )
        edge_rows = cur.fetchall()
        edge_cols = [d.name for d in cur.description]
    edge_dicts = [dict(zip(edge_cols, r)) for r in edge_rows]
    print(f"  collected {len(edge_dicts)} taxonomy_edges", file=sys.stderr)

    with conn.cursor() as cur:
        cur.execute(
            """
            select alias, node_id, created_at
            from taxonomy_aliases
            where node_id = any(%s)
            order by node_id, alias;
            """,
            (sorted_node_ids,),
        )
        alias_rows = cur.fetchall()
        alias_cols = [d.name for d in cur.description]
    alias_dicts = [dict(zip(alias_cols, r)) for r in alias_rows]
    print(f"  collected {len(alias_dicts)} taxonomy_aliases", file=sys.stderr)

    # ------------------------------------------------------------------
    # 7. Recipes themselves. Force cluster_id=NULL since we don't pull
    #    recipe_clusters into the fixture.
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, source_url, site, name, author, image_url, jsonld,
                   fetched_at, extracted_at, canonical_name, canonical_name_source,
                   normalizer_version, normalized_at, variant_key, dedup_version
            from recipes
            where id = any(%s)
            order by id;
            """,
            (recipe_ids,),
        )
        recipe_rows = cur.fetchall()
        recipe_cols = [d.name for d in cur.description]
    recipe_dicts = [dict(zip(recipe_cols, r)) for r in recipe_rows]

    # ------------------------------------------------------------------
    # 8. Assemble the SQL file.
    # ------------------------------------------------------------------
    today = dt.date.today().isoformat()
    out: list[str] = []
    out.append(_header(today))
    out.append("begin;\n")

    out.append(_section_taxonomy_nodes(node_dicts))
    out.append(_section_taxonomy_edges(edge_dicts))
    out.append(_section_taxonomy_aliases(alias_dicts))
    out.append(_section_recipes(recipe_dicts))
    out.append(_section_recipe_ingredients(ri_dicts, node_id_set))
    out.append(_section_taxonomy_proposals(proposal_rows))
    out.append(_section_sequences(
        node_dicts, recipe_dicts, ri_dicts, proposal_rows
    ))

    out.append("commit;\n")

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text("\n".join(out))
    print(f"\nwrote {FIXTURE_PATH}", file=sys.stderr)
    print(f"counts:", file=sys.stderr)
    print(f"  taxonomy_nodes     : {len(node_dicts)}", file=sys.stderr)
    print(f"  taxonomy_edges     : {len(edge_dicts)}", file=sys.stderr)
    print(f"  taxonomy_aliases   : {len(alias_dicts)}", file=sys.stderr)
    print(f"  recipes            : {len(recipe_dicts)}", file=sys.stderr)
    print(f"  recipe_ingredients : {len(ri_dicts)}", file=sys.stderr)
    print(f"  taxonomy_proposals : {len(proposal_rows)}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _header(today: str) -> str:
    return f"""-- E2E fixture for the /proposals review page.
--
-- Hand-curated from a staging-data restore: ~100 pending taxonomy
-- proposals + their referenced taxonomy nodes + matching recipes +
-- those recipes' ingredient lists. Designed so Create / Map / Flag
-- actions actually resolve recipe_ingredients rows end-to-end.
--
-- This file is NOT in supabase/config.toml's [db.seed].sql_paths, so
-- `supabase db reset` ignores it. Apply manually after `db reset`:
--
--   set -a && source /workspaces/spiritolo/.env && set +a
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 \\
--        -f supabase/seeds/e2e_proposals.fixture.sql
--
-- Idempotent against a fresh `db reset` (empty public schema + the
-- dev admin seed). NOT designed to layer on top of a staging restore
-- — IDs may collide. Use one or the other.
--
-- Generated {today}; refresh by re-running scripts/build-e2e-fixture.py
-- against a fresh local staging restore.
"""


def _section_taxonomy_nodes(rows: list[dict]) -> str:
    if not rows:
        return ""
    # Dedupe kebab-form slug collisions by suffixing the lower-id row's
    # slug with its id. Pre-cleanup snake/kebab pairs survived in the
    # data (e.g. `barolo_chinato` + `barolo-chinato` for distinct ids);
    # after kebab() they'd both become `barolo-chinato` and trip the
    # unique constraint.
    seen: dict[str, int] = {}
    sorted_rows = sorted(rows, key=lambda r: r["id"])
    for r in sorted_rows:
        k = kebab(r["slug"])
        if k in seen:
            # Second-seen-wins: suffix the current row, leave the prior.
            r["_emit_slug"] = f"{k}-{r['id']}"
        else:
            seen[k] = r["id"]
            r["_emit_slug"] = k

    lines = ["-- taxonomy_nodes ---------------------------------------"]
    for r in rows:
        lines.append(
            "insert into public.taxonomy_nodes "
            "(id, slug, display_name, node_kind, is_cluster_node, "
            "default_role, is_defining_garnish, created_at) values "
            f"({sql_lit(r['id'])}, {sql_lit(r['_emit_slug'])}, "
            f"{sql_lit(r['display_name'])}, {sql_lit(r['node_kind'])}, "
            f"{sql_lit(r['is_cluster_node'])}, {sql_lit(r['default_role'])}, "
            f"{sql_lit(r['is_defining_garnish'])}, {sql_lit(r['created_at'])});"
        )
    return "\n".join(lines) + "\n"


def _section_taxonomy_edges(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["-- taxonomy_edges ---------------------------------------"]
    for r in rows:
        lines.append(
            "insert into public.taxonomy_edges "
            "(parent_id, child_id, created_at) values "
            f"({sql_lit(r['parent_id'])}, {sql_lit(r['child_id'])}, "
            f"{sql_lit(r['created_at'])});"
        )
    return "\n".join(lines) + "\n"


def _section_taxonomy_aliases(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["-- taxonomy_aliases -------------------------------------"]
    for r in rows:
        lines.append(
            "insert into public.taxonomy_aliases "
            "(alias, node_id, created_at) values "
            f"({sql_lit(r['alias'])}, {sql_lit(r['node_id'])}, "
            f"{sql_lit(r['created_at'])});"
        )
    return "\n".join(lines) + "\n"


def _section_recipes(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["-- recipes ----------------------------------------------"]
    for r in rows:
        jsonld_lit = sql_lit(Jsonb(r["jsonld"]))
        lines.append(
            "insert into public.recipes "
            "(id, source_url, site, name, author, image_url, jsonld, "
            "fetched_at, extracted_at, canonical_name, canonical_name_source, "
            "normalizer_version, normalized_at, cluster_id, variant_key, "
            "dedup_version) values "
            f"({sql_lit(r['id'])}, {sql_lit(r['source_url'])}, "
            f"{sql_lit(r['site'])}, {sql_lit(r['name'])}, "
            f"{sql_lit(r['author'])}, {sql_lit(r['image_url'])}, "
            f"{jsonld_lit}, "
            f"{sql_lit(r['fetched_at'])}, {sql_lit(r['extracted_at'])}, "
            f"{sql_lit(r['canonical_name'])}, "
            f"{sql_lit(r['canonical_name_source'])}, "
            f"{sql_lit(r['normalizer_version'])}, "
            f"{sql_lit(r['normalized_at'])}, "
            f"NULL, "  # cluster_id forced NULL (no clusters in fixture)
            f"{sql_lit(r['variant_key'])}, {sql_lit(r['dedup_version'])});"
        )
    return "\n".join(lines) + "\n"


def _section_recipe_ingredients(rows: list[dict], node_id_set: set[int]) -> str:
    if not rows:
        return ""
    lines = ["-- recipe_ingredients -----------------------------------"]
    for r in rows:
        # Defensive: tax id must be in our node universe or NULL.
        tax_id = r["taxonomy_node_id"]
        if tax_id is not None and tax_id not in node_id_set:
            tax_id = None
        lines.append(
            "insert into public.recipe_ingredients "
            "(id, recipe_id, position, raw_text, amount, amount_max, unit, "
            "name, modifier, parse_status, parser_rule, parser_version, "
            "parsed_at, taxonomy_node_id, mapper_source, mapper_version, "
            "mapper_at, role, role_source, flag_reason) values "
            f"({sql_lit(r['id'])}, {sql_lit(r['recipe_id'])}, "
            f"{sql_lit(r['position'])}, {sql_lit(r['raw_text'])}, "
            f"{sql_lit(r['amount'])}, {sql_lit(r['amount_max'])}, "
            f"{sql_lit(r['unit'])}, {sql_lit(r['name'])}, "
            f"{sql_lit(r['modifier'])}, {sql_lit(r['parse_status'])}, "
            f"{sql_lit(r['parser_rule'])}, {sql_lit(r['parser_version'])}, "
            f"{sql_lit(r['parsed_at'])}, {sql_lit(tax_id)}, "
            f"{sql_lit(r['mapper_source'])}, {sql_lit(r['mapper_version'])}, "
            f"{sql_lit(r['mapper_at'])}, {sql_lit(r['role'])}, "
            f"{sql_lit(r['role_source'])}, {sql_lit(r['flag_reason'])});"
        )
    return "\n".join(lines) + "\n"


def _section_taxonomy_proposals(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["-- taxonomy_proposals -----------------------------------"]
    for r in rows:
        cand_lit = sql_lit(Jsonb(r["candidates"]))
        lines.append(
            "insert into public.taxonomy_proposals "
            "(id, raw_string, proposed_slug, proposed_display_name, "
            "proposed_parent_id, candidates, mapper_version, status, "
            "decided_by, decided_at, created_at) values "
            f"({sql_lit(r['id'])}, {sql_lit(r['raw_string'])}, "
            f"{sql_lit(kebab(r['proposed_slug']))}, "
            f"{sql_lit(r['proposed_display_name'])}, "
            f"{sql_lit(r['proposed_parent_id'])}, "
            f"{cand_lit}, "
            f"{sql_lit(r['mapper_version'])}, {sql_lit(r['status'])}, "
            f"{sql_lit(r['decided_by'])}, {sql_lit(r['decided_at'])}, "
            f"{sql_lit(r['created_at'])});"
        )
    return "\n".join(lines) + "\n"


def _section_sequences(
    nodes: list[dict],
    recipes: list[dict],
    ris: list[dict],
    proposals: list[dict],
) -> str:
    """Reset each touched sequence to max(id) of fixture rows."""
    lines = ["-- sequence resets --------------------------------------"]
    if nodes:
        lines.append(
            f"select setval('public.taxonomy_nodes_id_seq', "
            f"{max(r['id'] for r in nodes)}, true);"
        )
    if recipes:
        lines.append(
            f"select setval('public.recipes_id_seq', "
            f"{max(r['id'] for r in recipes)}, true);"
        )
    if ris:
        lines.append(
            f"select setval('public.recipe_ingredients_id_seq', "
            f"{max(r['id'] for r in ris)}, true);"
        )
    if proposals:
        lines.append(
            f"select setval('public.taxonomy_proposals_id_seq', "
            f"{max(r['id'] for r in proposals)}, true);"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
