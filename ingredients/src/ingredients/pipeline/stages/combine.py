"""combine-nodes stage — dedup/merge taxonomy nodes (entity kind ``taxonomy_node``).

``map-ingredient`` mechanically mints an unresolved ingredient name as a
``status='provisional'`` taxonomy node, so synonyms of the same substance land
as separate nodes ("lime juice" and "juice of 1 lime"). ``combine-nodes`` is the
whole-set harmonization pass that collapses those duplicates — the taxonomy
analogue of ``cluster-recipes`` (content-address, then merge duplicates).

For each node in the run's queue this stage generates a small DETERMINISTIC set
of merge candidates (other nodes that share a lexical signal, preferring
``status='live'`` ones), then asks the LLM tier whether the node names the SAME
underlying substance as one candidate. A confident ``merge`` repoints every
reference from the absorbed node to the survivor and deletes the absorbed node
(via ``taxonomy.combine_merge``); a ``distinct`` keeps the node; anything
uncertain (or no LLM available) opens a ``combine-nodes`` machine-proposal review
for a curator and parks the node as ``pending``. A node with no candidates at all
is trivially distinct — recorded ``resolved`` with no LLM call.

The blessed survivor prefers an existing live node: candidates are surfaced live
first, and the LLM is instructed to pick a live survivor when one fits, so a
provisional duplicate is absorbed into the established live node rather than the
reverse.
"""

from __future__ import annotations

from typing import Any

from common.db import Connection
from common.providers.packing import Item
from common.text import similarity
from ingredients.pipeline.stages import base
from ingredients.reviews.model import insert_review
from ingredients.taxonomy import TaxonomyError, combine_merge

STAGE = "combine-nodes"
# v2: per-item prompt + answer schema for the packed envelope.
COMBINE_VERSION = "v2"

# How many candidate nodes to surface per node, and the trigram-similarity floor
# for the lexical candidate signal. Kept small so each LLM item stays cheap.
MAX_CANDIDATES = 6
SIMILARITY_FLOOR = 0.3

COMBINE_PROMPT = """\
You deduplicate a cocktail-ingredient taxonomy. Each node names one substance a
recipe can call for (a spirit, juice, syrup, bitters, garnish, ...). Freshly
minted provisional nodes are often synonyms of a node that already exists.

Each item's `input` is a node — {"name", "slug", "candidates"} — where each
candidate node has a slug, display name, and status ('live' = established,
'provisional' = also freshly minted). Decide whether the node names the SAME
underlying substance as exactly one candidate. Each item's `answer` is ONE of
these two JSON objects:

1. MERGE — the node is a true synonym of one candidate (same substance):
   {"action": "merge", "survivor_slug": "<that candidate's slug>"}

2. DISTINCT — no candidate is the same substance:
   {"action": "distinct", "survivor_slug": null}

Rules:
- Merge only TRUE SYNONYMS — different names for the identical substance, e.g.
  "lime juice" == "juice of 1 lime", "angostura" == "aromatic bitters".
- Do NOT merge merely related, similar, or substitutable things: lime != lemon,
  bourbon != rye, "simple syrup" != "demerara syrup", "gin" != "old tom gin".
- When you do merge, PREFER a 'live' candidate as the survivor over a
  'provisional' one — the established node should absorb the duplicate.
- `survivor_slug` MUST be one of the candidate slugs exactly.
- Prefer "distinct" over a guess.
"""

COMBINE_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["merge", "distinct"]},
        "survivor_slug": {"type": ["string", "null"]},
    },
    "required": ["action", "survivor_slug"],
    "additionalProperties": False,
}


def _tokens(name: str) -> list[str]:
    """Significant lowercase tokens of a display name (>= 3 chars).

    Cheap lexical key for candidate generation: two nodes sharing a significant
    token ("juice", "lime") are plausible synonyms worth asking the LLM about.
    Splitting on non-alphanumerics matches the SQL side so Python-computed tokens
    and DB-computed tokens agree."""
    import re

    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) >= 3]


def _node_row(conn: Connection, node_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "select slug, display_name, status from taxonomy_nodes where id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return {"slug": row[0], "display_name": row[1], "status": row[2]}


def _all_nodes(conn: Connection) -> list[dict[str, Any]]:
    """Every node (id, slug, display_name, status) — the candidate universe."""
    return [
        {"id": r[0], "slug": r[1], "display_name": r[2], "status": r[3]}
        for r in conn.execute(
            "select id, slug, display_name, status from taxonomy_nodes"
        ).fetchall()
    ]


def _candidates(
    conn: Connection, node_id: int, display_name: str, slug: str,
    nodes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Up to ``MAX_CANDIDATES`` OTHER nodes that might be the same substance.

    Deterministic lexical signal, live-preferring: a candidate qualifies if its
    display name is trigram-similar (pg_trgm-compatible ``similarity`` >=
    ``SIMILARITY_FLOOR``) to this node's, OR it shares a significant token with
    it. Self is excluded and live nodes are surfaced first, so the LLM sees an
    established survivor before a provisional one. ``nodes`` is an optional
    pre-fetched snapshot (one query per run instead of one per node)."""
    tokens = set(_tokens(display_name))
    name = display_name or ""
    scored: list[tuple[int, float, str, dict[str, Any]]] = []
    for n in nodes if nodes is not None else _all_nodes(conn):
        if n["id"] == node_id:
            continue
        sim = similarity(n["display_name"], name)
        if sim < SIMILARITY_FLOOR and not (tokens and tokens & set(_tokens(n["display_name"]))):
            continue
        scored.append((0 if n["status"] == "live" else 1, -sim, n["slug"], n))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [
        {"slug": n["slug"], "display_name": n["display_name"], "status": n["status"]}
        for _, _, _, n in scored[:MAX_CANDIDATES]
    ]


def _node_id_for_slug(conn: Connection, slug: str) -> int | None:
    row = conn.execute(
        "select id from taxonomy_nodes where slug = ?", (slug,)
    ).fetchone()
    return row[0] if row else None


def _apply_answer(
    conn: Connection,
    *,
    job: dict[str, Any],
    node_id: int,
    candidates: list[dict[str, Any]],
    answer: Any,
    llm_attempted: bool,
    counts: dict[str, int],
) -> None:
    """Apply one LLM verdict to a node: merge / distinct / park-for-review."""
    job_id = job.get("id")
    cand_slugs = {c["slug"] for c in candidates}

    if isinstance(answer, dict) and answer.get("action") == "merge":
        survivor_slug = answer.get("survivor_slug")
        survivor_id = (
            _node_id_for_slug(conn, survivor_slug) if survivor_slug else None
        )
        # A valid merge names one of the surfaced candidates (never self). The
        # chosen candidate is the survivor (candidates are live-first, so an LLM
        # following the prompt blesses the live node); the current node is
        # absorbed into it.
        if (
            survivor_slug in cand_slugs
            and survivor_id is not None
            and survivor_id != node_id
        ):
            try:
                combine_merge(conn, survivor_id, node_id)
            except TaxonomyError:
                # The survivor vanished between candidate generation and now
                # (absorbed by an earlier merge in this run): uncertain, park it.
                survivor_id = None
        if survivor_id is not None and survivor_slug in cand_slugs and survivor_id != node_id:
            base.record_node(
                conn, node_id=node_id, stage=STAGE, version=COMBINE_VERSION,
                outcome="resolved", method="llm", job_id=job_id,
                payload={
                    "action": "merge",
                    "survivor_slug": survivor_slug,
                    "survivor_id": survivor_id,
                },
            )
            counts["merged"] += 1
            return
        # Fall through: an unusable merge answer (unknown/self slug) is uncertain.

    elif isinstance(answer, dict) and answer.get("action") == "distinct":
        base.record_node(
            conn, node_id=node_id, stage=STAGE, version=COMBINE_VERSION,
            outcome="resolved", method="llm", job_id=job_id,
            payload={"action": "distinct"},
        )
        counts["distinct"] += 1
        return

    # Uncertain, no answer, or no LLM available: open a curator review and park.
    insert_review(
        conn,
        entity_kind=base.ENTITY_TAXONOMY_NODE,
        entity_id=str(node_id),
        stage=STAGE,
        origin="machine_proposal",
        payload={"candidates": candidates},
        origin_version=COMBINE_VERSION,
    )
    base.record_node(
        conn, node_id=node_id, stage=STAGE, version=COMBINE_VERSION,
        outcome="pending", method="llm" if llm_attempted else "deterministic",
        job_id=job_id, payload={"candidates": candidates},
    )
    counts["pending"] += 1


def combine_stage_fn(
    job: dict[str, Any],
    conn: Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Merge duplicate taxonomy nodes across the run's node queue.

    Queue: a real run processes exactly its selected ``taxonomy_node`` members;
    the cold-build path pulls the NOT-EXISTS-a-run-at-this-version node queue,
    scoped to the provisional residue by default (``broad`` in the job payload
    widens it to the live set). Each node with no merge candidates is trivially
    distinct; the rest are judged by the LLM tier (packed in ``chunk_size``
    groups). Returns ``{"merged", "distinct", "pending"}`` counts."""
    _, limit = base.scope(job)
    broad = bool((job.get("payload") or {}).get("broad", False))
    if job.get("id"):
        node_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        node_ids = base.node_queue(
            conn, stage=STAGE, version=COMBINE_VERSION, broad=broad, limit=limit
        )

    counts = {"merged": 0, "distinct": 0, "pending": 0}

    # Pass 1 (deterministic): record trivially-distinct nodes (no candidates) now;
    # collect the rest as LLM items keyed by node id.
    node_candidates: dict[int, list[dict[str, Any]]] = {}
    items: list[Item] = []
    nodes = _all_nodes(conn) if node_ids else []
    for node_id in node_ids:
        info = _node_row(conn, node_id)
        if info is None:
            continue
        candidates = _candidates(conn, node_id, info["display_name"], info["slug"], nodes)
        if not candidates:
            base.record_node(
                conn, node_id=node_id, stage=STAGE, version=COMBINE_VERSION,
                outcome="resolved", method="deterministic", job_id=job.get("id"),
                payload={"candidates": []},
            )
            counts["distinct"] += 1
            continue
        node_candidates[node_id] = candidates
        items.append(
            Item(
                id=str(node_id),
                payload={
                    "name": info["display_name"],
                    "slug": info["slug"],
                    "candidates": candidates,
                },
            )
        )

    # Pass 2 (LLM tier): resolve the candidate-bearing nodes in packed chunks.
    resolved_by_llm: dict[str, Any] = {}
    llm_attempted = providers is not None and bool(items)
    if llm_attempted:
        for chunk in base.chunked(items, chunk_size):
            result = providers.resolve(
                chunk, system_prompt=COMBINE_PROMPT, answer_schema=COMBINE_ANSWER_SCHEMA
            )
            resolved_by_llm.update(result.resolved)

    # Pass 3: apply each verdict (merge / distinct / park). A node the merge just
    # absorbed is deleted, so later nodes referencing it as a candidate simply
    # fail the slug lookup and park — no stale merge.
    for node_id, candidates in node_candidates.items():
        _apply_answer(
            conn, job=job, node_id=node_id, candidates=candidates,
            answer=resolved_by_llm.get(str(node_id)),
            llm_attempted=llm_attempted, counts=counts,
        )
    return counts
