"""map stage — resolve ingredient names to taxonomy slugs (SHARED resolution).

Resolution is name-keyed, not per recipe row: a name resolves once into
`ingredient_resolutions (normalized_name -> taxonomy_slug)` and every recipe
that uses that name follows, so a taxonomy correction is a single-row edit. The
deterministic tier is the alias + lexical layers (which return a taxonomy node
id — joined to its slug here); misses route to the LLM tier (provider chain),
which may only attach a name to an existing node or abstain. Anything still
unresolved is mechanically minted as a provisional node (deterministic, no LLM),
so every non-garbage name ends up resolved to a live or provisional node. A
per-recipe `job_items` row records whether that recipe's names are all resolved
at `MAPPER_VERSION` while the resolutions themselves stay shared.
"""

from __future__ import annotations

from typing import Any

import psycopg

from common.providers.packing import Item
from ingredients.mapping.alias_layer import fetch_aliases_dict
from ingredients.mapping.lexical_layer import resolve_lexical
from ingredients.mapping.llm_actions import apply_llm_action
from ingredients.mapping.mint import mint_provisional_node
from ingredients.mapping.resolutions import write_abstain, write_resolution
from ingredients.mapping.types import Resolved
from ingredients.pipeline.stages import base

STAGE = "map-ingredient"
# v2: map no longer proposes/auto-creates taxonomy structure. Unresolved names
# now mint a provisional node (deterministic) instead of parking as pending.
MAPPER_VERSION = "v2"


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


def _resolve_names(
    conn: psycopg.Connection, names: list[str], aliases: dict[str, int], providers: Any
) -> None:
    """Resolve every name lacking a resolution at MAPPER_VERSION into the shared
    table: alias -> lexical -> LLM tier (existing node only) -> mint provisional.

    The LLM tier may only attach a name to an *existing* node (``chose_slug``) or
    abstain; it never proposes or creates structure. Any name the three tiers
    leave without a non-null slug is then mechanically minted as a provisional
    node — deterministically, needing no LLM — so this final pass runs regardless
    of whether ``providers`` was available (e.g. the CLI cold build). A name that
    can't produce a valid kebab slug falls back to a recorded abstain."""
    pending = [n for n in names if n not in _already_resolved(conn, names)]
    llm_names: list[str] = []
    for name in pending:
        node_id = aliases.get(name)
        if node_id is not None:
            write_resolution(
                conn, normalized_name=name, taxonomy_slug=_slug_for_node(conn, node_id),
                method="alias", version=MAPPER_VERSION,
            )
            continue
        result = resolve_lexical(conn, name)
        if isinstance(result, Resolved):
            write_resolution(
                conn, normalized_name=name,
                taxonomy_slug=_slug_for_node(conn, result.taxonomy_node_id),
                method="lexical", version=MAPPER_VERSION,
            )
            continue
        llm_names.append(name)

    resolved_by_llm: dict[str, Any] = {}
    if llm_names and providers is not None:
        # NB: unlike combine/connect/extract, map's LLM items are ingredient
        # *names* while its job_item entities are *recipes* — a name is shared
        # across every recipe that uses it. So the ChainResult's per-item
        # tokens/cost/model are deliberately NOT attributed to job_items here:
        # doing so would double-count a shared name across its recipes and
        # corrupt the run's token/cost roll-up.
        result = providers.resolve([Item(id=n, payload=n) for n in llm_names])
        resolved_by_llm = result.resolved
    for name in llm_names:
        apply_llm_action(
            conn, normalized_name=name, answer=resolved_by_llm.get(name),
            version=MAPPER_VERSION,
        )

    _mint_unresolved(conn, pending)


def _mint_unresolved(conn: psycopg.Connection, names: list[str]) -> None:
    """Mint a provisional node for every name in ``names`` still without a
    non-null resolution at MAPPER_VERSION. Deterministic — no LLM involved."""
    if not names:
        return
    rows = conn.execute(
        "select normalized_name from ingredient_resolutions "
        "where version = %s and taxonomy_slug is not null and normalized_name = any(%s)",
        (MAPPER_VERSION, names),
    ).fetchall()
    have = {r[0] for r in rows}
    for name in names:
        if name in have:
            continue
        slug = mint_provisional_node(
            conn, normalized_name=name, version=MAPPER_VERSION
        )
        if slug is None:
            write_abstain(conn, normalized_name=name, version=MAPPER_VERSION)


def _recipe_names(conn: psycopg.Connection, recipe_id: int) -> list[str]:
    rows = conn.execute(
        "select distinct lower(btrim(name)) from recipe_ingredients "
        "where recipe_id = %s and name is not null and btrim(name) <> ''",
        (recipe_id,),
    ).fetchall()
    return [r[0] for r in rows]


def map_stage_fn(
    job: dict[str, Any],
    conn: psycopg.Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Resolve every queued recipe's ingredient names into the shared resolution.

    DB I/O is batched per chunk: one bulk name fetch, one shared resolution pass
    over the chunk's deduped name union (so every name still resolves exactly
    once), one grouped resolved-count query, and one ledger executemany — all in
    a single transaction. Per-recipe outcome/count semantics are unchanged.
    """
    site, limit = base.scope(job)
    if job.get("id"):
        recipe_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        recipe_ids = base.recipe_queue(
            conn, stage=STAGE, version=MAPPER_VERSION, site=site, limit=limit
        )
    aliases = fetch_aliases_dict(conn) if recipe_ids else {}
    counts = {"resolved": 0, "pending": 0}

    for chunk in base.chunked(recipe_ids, chunk_size):
        # 1. Bulk-fetch names, building per-recipe DISTINCT lists (matching
        #    _recipe_names) and the deduped union across the chunk.
        per_recipe: dict[int, dict[str, None]] = {rid: {} for rid in chunk}
        for rid, name in conn.execute(
            "select recipe_id, lower(btrim(name)) from recipe_ingredients "
            "where recipe_id = any(%s) and name is not null and btrim(name) <> ''",
            (chunk,),
        ).fetchall():
            per_recipe[rid][name] = None
        recipe_names = {rid: list(d) for rid, d in per_recipe.items()}
        union_names = list({n: None for names in recipe_names.values() for n in names})

        # 2. Resolve the union once (shared, resolve-each-name-once). This stays
        #    outside the chunk transaction: the shared resolution helpers own
        #    their own writes on the autocommit connection, exactly as when the
        #    per-recipe loop ran them.
        _resolve_names(conn, union_names, aliases, providers)

        # Pin: re-stamp any human overrides the auto-resolution just clobbered,
        # supersede machine proposals now resolved, and point map's live version.
        base.finalize_run(conn, stage=STAGE, version=MAPPER_VERSION, ids=union_names)

        with conn.transaction():
            # 3. One grouped count query -> resolved row count per name.
            name_counts: dict[str, int] = {}
            if union_names:
                for name, cnt in conn.execute(
                    "select normalized_name, count(*) from ingredient_resolutions "
                    "where taxonomy_slug is not null and normalized_name = any(%s) "
                    "group by normalized_name",
                    (union_names,),
                ).fetchall():
                    name_counts[name] = cnt

            # 4. Per-recipe outcome, counts, and accumulated ledger records.
            records: list[dict[str, Any]] = []
            for recipe_id in chunk:
                names = recipe_names[recipe_id]
                resolved_slugs = sum(name_counts.get(n, 0) for n in names)
                outcome = "resolved" if names and resolved_slugs == len(names) else "pending"
                counts["resolved" if outcome == "resolved" else "pending"] += 1
                records.append(
                    {
                        "recipe_id": recipe_id,
                        "stage": STAGE,
                        "version": MAPPER_VERSION,
                        "outcome": outcome,
                        "method": "deterministic",
                        "job_id": job.get("id"),
                        "payload": {"names": len(names), "resolved": resolved_slugs},
                    }
                )

            # 5. One ledger executemany for the chunk.
            base.record_many(conn, records)
    return counts
