"""map stage — resolve ingredient names to taxonomy slugs (SHARED resolution).

Resolution is name-keyed, not per recipe row: a name resolves once into
`ingredient_resolutions (normalized_name -> taxonomy_slug)` and every recipe
that uses that name follows, so a taxonomy correction is a single-row edit. The
deterministic tier is the alias + lexical layers (which return a taxonomy node
id — joined to its slug here); misses route to the LLM tier (provider chain),
which returns a slug or abstains. A per-recipe `stage_runs` row records whether
that recipe's names are all resolved at `MAPPER_VERSION` while the resolutions
themselves stay shared.
"""

from __future__ import annotations

from typing import Any

import psycopg

from common.providers.packing import Item
from ingredients.mapping.alias_layer import fetch_aliases_dict
from ingredients.mapping.lexical_layer import resolve_lexical
from ingredients.mapping.types import Resolved
from ingredients.pipeline.stages import base

STAGE = "map"
MAPPER_VERSION = "v1"


def _slug_for_node(conn: psycopg.Connection, node_id: int) -> str | None:
    row = conn.execute(
        "select slug from taxonomy_nodes where id = %s", (node_id,)
    ).fetchone()
    return row[0] if row else None


def _already_resolved(conn: psycopg.Connection, names: list[str]) -> set[str]:
    """Normalized names that already have a resolution row at MAPPER_VERSION."""
    if not names:
        return set()
    rows = conn.execute(
        "select normalized_name from ingredient_resolutions "
        "where version = %s and normalized_name = any(%s)",
        (MAPPER_VERSION, names),
    ).fetchall()
    return {r[0] for r in rows}


def _write_resolution(
    conn: psycopg.Connection, name: str, slug: str | None, method: str
) -> None:
    conn.execute(
        """
        insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version)
        values (%s, %s, %s, %s)
        on conflict (normalized_name) do update set
            taxonomy_slug = excluded.taxonomy_slug,
            method        = excluded.method,
            version       = excluded.version,
            updated_at    = now()
        """,
        (name, slug, method, MAPPER_VERSION),
    )


def _resolve_names(
    conn: psycopg.Connection, names: list[str], aliases: dict[str, int], providers: Any
) -> None:
    """Resolve every name lacking a resolution at MAPPER_VERSION into the shared
    table: alias -> lexical -> LLM tier -> abstain."""
    pending = [n for n in names if n not in _already_resolved(conn, names)]
    llm_names: list[str] = []
    for name in pending:
        node_id = aliases.get(name)
        if node_id is not None:
            _write_resolution(conn, name, _slug_for_node(conn, node_id), "alias")
            continue
        result = resolve_lexical(conn, name)
        if isinstance(result, Resolved):
            _write_resolution(conn, name, _slug_for_node(conn, result.taxonomy_node_id), "lexical")
            continue
        llm_names.append(name)

    resolved_by_llm: dict[str, Any] = {}
    if llm_names and providers is not None:
        result = providers.resolve([Item(id=n, payload=n) for n in llm_names])
        resolved_by_llm = result.resolved
    for name in llm_names:
        slug = resolved_by_llm.get(name)
        _write_resolution(conn, name, slug, "llm" if slug else "abstain")


def _recipe_names(conn: psycopg.Connection, recipe_id: int) -> list[str]:
    rows = conn.execute(
        "select distinct lower(btrim(name)) from recipe_ingredients "
        "where recipe_id = %s and name is not null and btrim(name) <> ''",
        (recipe_id,),
    ).fetchall()
    return [r[0] for r in rows]


def map_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Resolve every queued recipe's ingredient names into the shared resolution."""
    site, limit = base.scope(job)
    recipe_ids = base.recipe_queue(
        conn, stage=STAGE, version=MAPPER_VERSION, site=site, limit=limit
    )
    aliases = fetch_aliases_dict(conn) if recipe_ids else {}
    counts = {"resolved": 0, "pending": 0}

    for recipe_id in recipe_ids:
        names = _recipe_names(conn, recipe_id)
        _resolve_names(conn, names, aliases, providers)

        # Does this recipe now have a taxonomy slug for every name?
        resolved_slugs = conn.execute(
            "select count(*) from ingredient_resolutions "
            "where taxonomy_slug is not null and normalized_name = any(%s)",
            (names,),
        ).fetchone()[0] if names else 0
        outcome = "resolved" if names and resolved_slugs == len(names) else "pending"
        counts["resolved" if outcome == "resolved" else "pending"] += 1
        base.record(
            conn,
            recipe_id=recipe_id,
            stage=STAGE,
            version=MAPPER_VERSION,
            outcome=outcome,
            method="deterministic",
            job_id=job.get("id"),
            payload={"names": len(names), "resolved": resolved_slugs},
        )
    return counts
