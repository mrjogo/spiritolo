"""connect-nodes stage — place a provisional taxonomy node in the DAG + promote.

`map-ingredient` mints unresolved ingredient names as provisional
`taxonomy_nodes` (``status='provisional'``, ``node_kind`` NULL, no parent edge);
`combine-nodes` merges the duplicates. This stage does the remaining structural
judgment: for each surviving provisional node it asks the LLM tier which existing
parent(s) the node belongs under, what its ``node_kind`` is (a manufacturer brand
line → ``'brand'``, a specific SKU → ``'expression'``, or a plain
substance/category → ``NULL``), and whether it is a cluster-identity node. The
placement + promotion is the ``taxonomy.connect_place`` action, which attaches the
parent edges, enforces the antichain invariant, and flips ``status`` to
``'live'``.

The judgment is curator-sensitive, so anything the LLM can't confidently place —
no answer, an explicit ``uncertain``, an empty parent set, or a placement
``connect_place`` *rejects* (unknown parent slug / antichain violation) — opens a
``connect-nodes`` ``machine_proposal`` review and parks the node ``provisional``
for a human, exactly as the design's "curator-sensitive calls open a connect
review." Candidate parents are generated deterministically (cheap lexical +
trigram signal over the live nodes) so the model chooses from a real shortlist
rather than inventing structure.
"""

from __future__ import annotations

import re
from typing import Any

from common.db import Connection, jlist
from common.providers.packing import Item
from common.text import similarity
from ingredients.pipeline.stages import base
from ingredients.reviews.model import insert_review
from ingredients.taxonomy import TaxonomyError, connect_place

STAGE = "connect-nodes"
# v2: per-item prompt + answer schema for the packed envelope.
CONNECT_VERSION = "v2"

# How many candidate parents to surface to the model per node.
_CANDIDATE_LIMIT = 8

_NODE_KINDS = {"brand", "expression"}


CONNECT_PROMPT = """\
You place a NEW node into a cocktail-ingredient taxonomy DAG.

The taxonomy is a directed acyclic graph of canonical ingredients: broad
categories and definitional types at the top (e.g. "spirits", "whiskey",
"citrus"), concrete substances and fresh ingredients below them (e.g. "bourbon",
"lime juice", "demerara syrup"), and manufacturer brands / specific product
releases at the leaves (e.g. "buffalo trace", "eagle rare 10").

Each item's `input` is one node to place — {"name", "slug",
"candidate_parents"} — where candidate_parents lists nodes already live in the
taxonomy, each with a slug and display name: plausible broader categories the
node could sit under.

Each item's `answer` is ONE of these two JSON objects:

1. PLACE the node — give the parent slug(s) it belongs directly under, its
   node_kind, and whether it is a cluster-identity node:
   {"action": "place",
    "node_kind": "brand"|"expression"|null,
    "parent_slugs": ["<parent-slug>", ...],
    "is_cluster_node": false}

2. ABSTAIN when you cannot confidently place it (no good parent, unsure of kind):
   {"action": "uncertain", "node_kind": null, "parent_slugs": [],
    "is_cluster_node": false}

Rules:
- node_kind is STRUCTURAL: "brand" for a manufacturer's brand line, "expression"
  for a specific SKU / release, and null for everything else — a plain substance,
  a fresh ingredient, or a category/type. Most nodes are null.
- parent_slugs must be non-empty and should come from the provided candidates.
  Only reach outside the candidates for a well-known existing slug you are
  certain exists; a wrong slug parks the node for a human.
- is_cluster_node is almost always false. The cluster antichain is
  curator-controlled — default false and only set true when you are certain the
  node is itself a drink-identity category with no cluster ancestor.
- Prefer "uncertain" over guessing.
"""

CONNECT_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["place", "uncertain"]},
        "node_kind": {"type": ["string", "null"], "enum": ["brand", "expression", None]},
        "parent_slugs": {"type": "array", "items": {"type": "string"}},
        "is_cluster_node": {"type": "boolean"},
    },
    "required": ["action", "node_kind", "parent_slugs", "is_cluster_node"],
    "additionalProperties": False,
}


def _tokens(name: str) -> list[str]:
    """Alphanumeric tokens of a node name (>= 2 chars), lowercased."""
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) >= 2]


def _live_nodes(conn: Connection) -> list[dict[str, Any]]:
    """Live nodes (id, slug, display_name) — the parent candidate universe."""
    return [
        {"id": r[0], "slug": r[1], "display_name": r[2]}
        for r in conn.execute(
            "select id, slug, display_name from taxonomy_nodes where status = 'live'"
        ).fetchall()
    ]


def _candidate_parents(
    conn: Connection, *, node_id: int, name: str, slug: str,
    live: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Deterministic shortlist of up to ``_CANDIDATE_LIMIT`` live nodes that could
    be a parent of ``node_id``.

    Cheap lexical signal: a live node whose display name or slug shares a token
    with the node's name (so provisional "lime juice" surfaces "lime", "juice"),
    OR whose display name is trigram-similar to the node's name. Token hits rank
    above pure similarity. Excludes the node itself and any non-live node —
    connect only attaches under already-placed (live) parents. ``live`` is an
    optional pre-fetched snapshot of the live set.
    """
    query_text = name or slug.replace("-", " ")
    tokens = set(_tokens(name))
    scored: list[tuple[int, float, str, dict[str, Any]]] = []
    for n in live if live is not None else _live_nodes(conn):
        if n["id"] == node_id:
            continue
        name_hit = bool(tokens and tokens & set(_tokens(n["display_name"])))
        slug_hit = bool(tokens and tokens & set(_tokens(n["slug"])))
        sim = similarity(n["display_name"], query_text)
        if not (name_hit or slug_hit or sim >= 0.35):
            continue
        scored.append((0 if name_hit else 1, -sim, n["slug"], n))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [{"slug": n["slug"], "display_name": n["display_name"]} for _, _, _, n in scored[:_CANDIDATE_LIMIT]]


def _park(
    conn: Connection,
    *,
    node_id: int,
    candidates: list[dict[str, str]],
    job_id: int | None,
    payload: dict[str, Any],
) -> None:
    """Open a connect-nodes machine-proposal review and record the node pending.

    The node stays ``provisional`` (nothing was written to the DAG); the review
    hands the placement decision to a curator, and the ``pending`` outcome flags
    the entity's job_item."""
    insert_review(
        conn,
        entity_kind=base.ENTITY_TAXONOMY_NODE,
        entity_id=str(node_id),
        stage=STAGE,
        origin="machine_proposal",
        payload=payload,
        origin_version=CONNECT_VERSION,
    )
    base.record_node(
        conn,
        node_id=node_id,
        stage=STAGE,
        version=CONNECT_VERSION,
        outcome="pending",
        method="llm",
        job_id=job_id,
        payload=payload,
    )


def _apply_answer(
    conn: Connection,
    *,
    node_id: int,
    answer: Any,
    candidates: list[dict[str, str]],
    job_id: int | None,
) -> str:
    """Apply one node's LLM answer. Returns ``"connected"`` or ``"pending"``.

    On a well-formed placement it calls ``taxonomy.connect_place``, which
    attaches parent edges, enforces the antichain invariant, and promotes the
    node to ``live`` inside its own savepoint. If it raises (unknown parent slug
    or antichain violation), the savepoint rolls back — so no partial edge
    survives — and the node is parked for review. A missing
    answer, an explicit ``uncertain``, or an empty parent set parks it too."""
    if not isinstance(answer, dict) or answer.get("action") == "uncertain":
        _park(
            conn,
            node_id=node_id,
            candidates=candidates,
            job_id=job_id,
            payload={"candidate_parents": candidates},
        )
        return "pending"

    node_kind = answer.get("node_kind")
    if node_kind not in _NODE_KINDS:
        # Structural nodes (categories, types, fresh ingredients) — and any
        # off-vocabulary kind the model returns — take NULL. The DB CHECK only
        # allows brand/expression/NULL.
        node_kind = None
    parent_slugs = [
        s for s in (answer.get("parent_slugs") or []) if isinstance(s, str) and s.strip()
    ]
    is_cluster_node = bool(answer.get("is_cluster_node", False))

    if not parent_slugs:
        _park(
            conn,
            node_id=node_id,
            candidates=candidates,
            job_id=job_id,
            payload={"candidate_parents": candidates},
        )
        return "pending"

    proposed = {
        "node_kind": node_kind,
        "parent_slugs": parent_slugs,
        "is_cluster_node": is_cluster_node,
    }
    try:
        # connect_place runs in its own savepoint and raises TaxonomyError on an
        # unknown parent slug or an antichain violation, rolling back any edge it
        # attached — so we fall through to review with nothing half-written.
        connect_place(conn, node_id, node_kind, parent_slugs, is_cluster_node)
    except TaxonomyError:
        _park(
            conn,
            node_id=node_id,
            candidates=candidates,
            job_id=job_id,
            payload={"candidate_parents": candidates, "proposed": proposed},
        )
        return "pending"

    base.record_node(
        conn,
        node_id=node_id,
        stage=STAGE,
        version=CONNECT_VERSION,
        outcome="resolved",
        method="llm",
        job_id=job_id,
        payload=proposed,
    )
    return "connected"


def connect_stage_fn(
    job: dict[str, Any],
    conn: Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Place + promote each queued provisional taxonomy node.

    Queue: a real run processes exactly the ``taxonomy_node`` entities the
    operator loaded (``run_item_ids``); the cold-build / queue path takes the
    provisional residue with no run at ``CONNECT_VERSION`` (``broad`` on the job
    payload widens it to the live set — see the design's "connect can run
    broadly"). Per chunk it builds one LLM request over the nodes' candidate
    parents, then applies each answer (place-and-promote or park-for-review).
    Returns ``{"connected": .., "pending": ..}``."""
    _site, limit = base.scope(job)
    if job.get("id"):
        node_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        broad = bool((job.get("payload") or {}).get("broad", False))
        node_ids = base.node_queue(
            conn, stage=STAGE, version=CONNECT_VERSION, broad=broad, limit=limit
        )

    counts = {"connected": 0, "pending": 0}
    for chunk in base.chunked(node_ids, chunk_size):
        meta = {
            r[0]: {"slug": r[1], "name": r[2]}
            for r in conn.execute(
                "select id, slug, display_name from taxonomy_nodes "
                "where id in (select value from json_each(?))",
                (jlist(chunk),),
            ).fetchall()
        }
        cand_by_node: dict[int, list[dict[str, str]]] = {}
        items: list[Item] = []
        live = _live_nodes(conn)
        for nid in chunk:
            info = meta.get(nid)
            if info is None:
                continue  # node vanished (e.g. absorbed by combine) — skip
            cands = _candidate_parents(
                conn, node_id=nid, name=info["name"], slug=info["slug"], live=live
            )
            cand_by_node[nid] = cands
            items.append(
                Item(
                    id=str(nid),
                    payload={
                        "name": info["name"],
                        "slug": info["slug"],
                        "candidate_parents": cands,
                    },
                )
            )

        answers: dict[str, Any] = {}
        if providers is not None and items:
            answers = providers.resolve(
                items, system_prompt=CONNECT_PROMPT, answer_schema=CONNECT_ANSWER_SCHEMA
            ).resolved

        for nid in chunk:
            if nid not in cand_by_node:
                continue
            outcome = _apply_answer(
                conn,
                node_id=nid,
                answer=answers.get(str(nid)),
                candidates=cand_by_node[nid],
                job_id=job.get("id"),
            )
            counts["connected" if outcome == "connected" else "pending"] += 1

    return counts
