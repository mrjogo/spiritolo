"""connect-nodes stage — place a provisional taxonomy node in the DAG + promote.

`map-ingredient` mints unresolved ingredient names as provisional
`taxonomy_nodes` (``status='provisional'``, ``node_kind`` NULL, no parent edge);
`combine-nodes` merges the duplicates. This stage does the remaining structural
judgment: for each surviving provisional node it asks the LLM tier which existing
parent(s) the node belongs under, what its ``node_kind`` is (a manufacturer brand
line → ``'brand'``, a specific SKU → ``'expression'``, or a plain
substance/category → ``NULL``), and whether it is a cluster-identity node. The
placement + promotion is the SQL ``connect_place`` action, which attaches the
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

import psycopg

from common.providers.packing import Item
from ingredients.pipeline.stages import base
from ingredients.reviews.model import insert_review

STAGE = "connect-nodes"
CONNECT_VERSION = "v1"

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

You receive one node to place:
- its name and slug,
- a list of CANDIDATE PARENT nodes already live in the taxonomy, each with a slug
  and display name — plausible broader categories the node could sit under.

Return a single JSON object, no commentary, choosing ONE of:

1. PLACE the node — give the parent slug(s) it belongs directly under, its
   node_kind, and whether it is a cluster-identity node:
   {"node_kind": "brand"|"expression"|null,
    "parent_slugs": ["<parent-slug>", ...],
    "is_cluster_node": false}

2. ABSTAIN when you cannot confidently place it (no good parent, unsure of kind):
   {"action": "uncertain"}

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
- Prefer {"action": "uncertain"} over guessing.
- Output JSON only. No prose, no markdown fences.
"""


def _tokens(name: str) -> list[str]:
    """Alphanumeric tokens of a node name (>= 2 chars), lowercased."""
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) >= 2]


def _candidate_parents(
    conn: psycopg.Connection, *, node_id: int, name: str, slug: str
) -> list[dict[str, str]]:
    """Deterministic shortlist of up to ``_CANDIDATE_LIMIT`` live nodes that could
    be a parent of ``node_id``.

    Cheap lexical signal: a live node whose display name or slug shares a token
    with the node's name (so provisional "lime juice" surfaces "lime", "juice"),
    OR whose display name is trigram-similar (``pg_trgm``) to the node's name.
    Token hits rank above pure similarity. Excludes the node itself and any
    non-live node — connect only attaches under already-placed (live) parents.
    """
    query_text = name or slug.replace("-", " ")
    rows = conn.execute(
        """
        select n.slug, n.display_name
        from taxonomy_nodes n
        where n.status = 'live'
          and n.id <> %(nid)s
          and (
                %(tokens)s::text[] && string_to_array(lower(n.display_name), ' ')
             or %(tokens)s::text[] && string_to_array(replace(lower(n.slug), '-', ' '), ' ')
             or similarity(n.display_name, %(q)s) >= 0.35
          )
        order by
          (%(tokens)s::text[] && string_to_array(lower(n.display_name), ' ')) desc,
          similarity(n.display_name, %(q)s) desc,
          n.slug
        limit %(lim)s
        """,
        {
            "nid": node_id,
            "tokens": _tokens(name),
            "q": query_text,
            "lim": _CANDIDATE_LIMIT,
        },
    ).fetchall()
    return [{"slug": r[0], "display_name": r[1]} for r in rows]


def _park(
    conn: psycopg.Connection,
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
    conn: psycopg.Connection,
    *,
    node_id: int,
    answer: Any,
    candidates: list[dict[str, str]],
    job_id: int | None,
) -> str:
    """Apply one node's LLM answer. Returns ``"connected"`` or ``"pending"``.

    On a well-formed placement it calls ``connect_place`` inside a savepoint
    (``with conn.transaction()``): the SQL attaches parent edges, enforces the
    antichain invariant, and promotes the node to ``live``. If ``connect_place``
    RAISES (unknown parent slug or antichain violation), the savepoint rolls back
    — so no partial edge survives — and the node is parked for review. A missing
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
        # Savepoint: connect_place raises on an unknown parent slug or an
        # antichain violation. Wrapping it keeps that RAISE from poisoning the
        # rest of the chunk — the block rolls back and we fall through to review.
        with conn.transaction():
            conn.execute(
                "select connect_place(%s, %s, %s, %s)",
                (node_id, node_kind, parent_slugs, is_cluster_node),
            )
    except psycopg.Error:
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
    conn: psycopg.Connection,
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
                "select id, slug, display_name from taxonomy_nodes where id = any(%s)",
                (chunk,),
            ).fetchall()
        }
        cand_by_node: dict[int, list[dict[str, str]]] = {}
        items: list[Item] = []
        for nid in chunk:
            info = meta.get(nid)
            if info is None:
                continue  # node vanished (e.g. absorbed by combine) — skip
            cands = _candidate_parents(
                conn, node_id=nid, name=info["name"], slug=info["slug"]
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
            answers = providers.resolve(items, system_prompt=CONNECT_PROMPT).resolved

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
