"""Phase 2 orchestrator. Drains the pending_llm queue using a chosen provider.

Branching by LLM action:

  chose          -> write_resolution(source='llm')
  propose_brand  -> insert taxonomy_node + edge + provenance, then resolve
  propose_form   -> enqueue_form_proposal; row stays pending_llm for review
  abstain        -> write_abstain
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg

from common.llm import LLMProvider
from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)
from common.llm.retry import resolve_with_retry as _resolve_with_retry_helper

from .db import fetch_pending_llm_names, write_abstain, write_resolution
from .lexical_layer import lexical_candidates
from .mapper import MAPPER_VERSION
from .normalize import normalize_name
from .prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)
from .proposals import enqueue_form_proposal

log = logging.getLogger("mapper")


def _candidates_with_parents(
    conn: psycopg.Connection, normalized: str, limit: int = 20,
) -> list[dict]:
    cands = lexical_candidates(conn, normalized, limit=limit)
    if not cands:
        return []
    ids_tuple = tuple({c["node_id"] for c in cands})
    parent_rows = conn.execute(
        """
        select e.child_id, n.slug
        from taxonomy_edges e
        join taxonomy_nodes n on n.id = e.parent_id
        where e.child_id = any(%s)
        """,
        (list(ids_tuple),),
    ).fetchall()
    parents_by_child: dict[int, list[str]] = {}
    for child, slug in parent_rows:
        parents_by_child.setdefault(child, []).append(slug)
    for c in cands:
        c["parents"] = parents_by_child.get(c["node_id"], [])
    return cands


def _lookup_node_by_slug(conn: psycopg.Connection, slug: str) -> int | None:
    row = conn.execute(
        "select id from taxonomy_nodes where slug = %s", (slug,),
    ).fetchone()
    return row[0] if row else None


def _node_exists(conn: psycopg.Connection, node_id: int) -> bool:
    row = conn.execute(
        "select 1 from taxonomy_nodes where id = %s", (node_id,),
    ).fetchone()
    return row is not None


# taxonomy_nodes.node_kind has a CHECK constraint allowing only these values
# (plus NULL). LLM-proposed brand/expression nodes must validate before INSERT
# or the whole transaction aborts.
_VALID_NODE_KINDS = {"brand", "expression"}


def _create_brand_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    display_name: str,
    parent_id: int,
    node_kind: str,
    raw_string: str,
    prompt_hash_value: str,
    model_id: str,
) -> int:
    """Insert the new node + edge + provenance. is_cluster_node defaults
    to false (E's column); the antichain stays curator-controlled.

    Slug collisions (two batch results proposing the same slug) resolve
    silently to the existing node. This is the right behavior in batch
    mode where prompts are built against a frozen candidate set: the
    second proposer agrees with the first and we map the row to the
    already-created node. Edge + provenance inserts are also tolerant
    of duplicates (ON CONFLICT DO NOTHING) so re-encountering the same
    (slug, raw_string) pair is idempotent."""
    row = conn.execute(
        "insert into taxonomy_nodes (slug, display_name, node_kind) "
        "values (%s, %s, %s) "
        "on conflict (slug) do nothing returning id",
        (slug, display_name, node_kind),
    ).fetchone()
    if row is None:
        # Existing node with this slug — resolve to it.
        new_id = conn.execute(
            "select id from taxonomy_nodes where slug = %s", (slug,),
        ).fetchone()[0]
    else:
        new_id = row[0]
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s) "
        "on conflict do nothing",
        (parent_id, new_id),
    )
    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, prompt_hash, model_id)
        values (%s, 'llm-mapper', %s, %s, %s, %s)
        on conflict do nothing
        """,
        (new_id, MAPPER_VERSION, raw_string, prompt_hash_value, model_id),
    )
    # NOTE: no conn.commit() here — the caller's write_resolution() commit
    # covers the whole unit (node + edge + provenance + row update) atomically.
    return new_id


def run_phase2(
    conn: psycopg.Connection,
    *,
    provider: LLMProvider,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Drain the pending_llm queue. Returns Counter-shaped summary keyed by action."""
    from common.interrupt import InterruptHandler
    from common.progress import make_progress
    counts: Counter[str] = Counter()
    names = fetch_pending_llm_names(conn, mapper_version=MAPPER_VERSION, limit=limit)
    total = len(names)
    if total == 0:
        log.info("nothing pending; queue is empty")
        return dict(counts)
    log.info("Phase 2: resolving %d distinct names via %s", total, provider.model_id)
    progress = make_progress(total=total)
    with InterruptHandler() as interrupt:
        for idx, normalized in enumerate(names, start=1):
            if interrupt.requested:
                # First Ctrl-C: in-flight LLM call (if any) has already
                # finished and its result was written by per-call commit.
                # Stop before paying for the next one.
                break
            cands = _candidates_with_parents(conn, normalized)
            user_prompt = build_user_prompt(
                normalized_name=normalized, parser_unit=None, site=site, candidates=cands,
            )
            action_obj = _resolve_with_retry_helper(
                provider,
                system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
                normalized_name=normalized,
                parse_fn=parse_response,    # already imported from .prompt above
            )
            if action_obj is None:
                # All retries exhausted; leave row at pending_llm and move on.
                counts["error"] += 1
                progress(idx)
                continue
            action = action_obj["action"]

            if action == "chose":
                node_id = int(action_obj["node_id"])
                if not _node_exists(conn, node_id):
                    log.warning(
                        "LLM chose node_id=%d which is not in taxonomy_nodes "
                        "for %r — abstaining (likely hallucination)",
                        node_id, normalized,
                    )
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    counts["abstain"] += 1
                    progress(idx)
                    continue
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=node_id,
                    source="llm", mapper_version=MAPPER_VERSION,
                )
                counts["chose"] += 1
            elif action == "propose_brand":
                node_kind = action_obj.get("node_kind")
                if node_kind not in _VALID_NODE_KINDS:
                    log.warning(
                        "LLM proposed invalid node_kind=%r for %r "
                        "(must be 'brand' or 'expression') — abstaining",
                        node_kind, normalized,
                    )
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    counts["abstain"] += 1
                    progress(idx)
                    continue
                parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
                if parent_id is None:
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    counts["abstain"] += 1
                    progress(idx)
                    continue
                # _create_brand_node + write_resolution must be atomic: the node,
                # edge, provenance, and recipe_ingredients update land in ONE
                # transaction. If write_resolution raises, we roll back so we
                # don't leak an orphan taxonomy node.
                try:
                    new_id = _create_brand_node(
                        conn,
                        slug=action_obj["slug"],
                        display_name=action_obj["display_name"],
                        parent_id=parent_id,
                        node_kind=node_kind,
                        raw_string=normalized,
                        prompt_hash_value=prompt_hash(normalized, None, site, cands),
                        model_id=provider.model_id,
                    )
                    write_resolution(
                        conn, normalized_name=normalized, taxonomy_node_id=new_id,
                        source="llm", mapper_version=MAPPER_VERSION,
                    )
                except Exception:
                    conn.rollback()
                    raise
                counts["propose_brand"] += 1
            elif action == "propose_form":
                parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
                enqueue_form_proposal(
                    conn,
                    raw_string=normalized,
                    proposed_slug=action_obj["slug"],
                    proposed_display_name=action_obj["display_name"],
                    proposed_parent_id=parent_id,
                    candidates=cands,
                    mapper_version=MAPPER_VERSION,
                )
                # Row stays pending_llm awaiting human review.
                counts["propose_form"] += 1
            elif action == "abstain":
                write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                counts["abstain"] += 1
            progress(idx)
    return dict(counts)


def submit_phase2_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batches_dir,
    site: str | None = None,
    limit: int | None = None,
) -> BatchSubmitOutcome:
    """Submit pending names as an OpenAI batch. Returns the submission +
    sidecar path. Caller (CLI) prints the batch_id and exits."""
    from common.progress import make_progress
    from .lexical_layer import bulk_lexical_candidates

    names = fetch_pending_llm_names(conn, mapper_version=MAPPER_VERSION, limit=limit)
    if not names:
        raise RuntimeError("nothing pending; queue is empty")
    total = len(names)

    log.info("fetching lexical candidates for %d distinct names…", total)
    candidates_by_name = bulk_lexical_candidates(conn, names)
    all_node_ids = sorted({
        c["node_id"] for cands in candidates_by_name.values() for c in cands
    })

    log.info("fetching parent slugs for %d candidate nodes…", len(all_node_ids))
    parents_by_child: dict[int, list[str]] = {}
    if all_node_ids:
        parent_rows = conn.execute(
            """
            select e.child_id, n.slug
            from taxonomy_edges e
            join taxonomy_nodes n on n.id = e.parent_id
            where e.child_id = any(%s)
            """,
            (all_node_ids,),
        ).fetchall()
        for child, slug in parent_rows:
            parents_by_child.setdefault(child, []).append(slug)

    log.info("building %d prompts…", total)
    progress = make_progress(total=total)
    rows = []
    for idx, n in enumerate(names, start=1):
        cands = candidates_by_name.get(n, [])
        for c in cands:
            c["parents"] = parents_by_child.get(c["node_id"], [])
        user_prompt = build_user_prompt(
            normalized_name=n, parser_unit=None, site=site, candidates=cands,
        )
        rows.append((n, SYSTEM_PROMPT, user_prompt))
        progress(idx)

    log.info("submitting %d-request batch to %s…", total, provider.model_id)
    return submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(
            custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2],
        ),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=MAPPER_VERSION,
        batches_dir=batches_dir,
    )


def ingest_phase2_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batch_id: str,
    batches_dir,
) -> dict[str, int]:
    """Ingest a previously submitted batch's results. Per-row writes go
    through the same write_resolution / write_abstain / propose_brand
    paths as run_phase2."""

    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        if error or raw_text is None:
            log.warning("batch result error for %r: %s", row_id, error)
            return
        try:
            action_obj = parse_response(raw_text)
        except Exception as exc:
            log.warning("batch result parse failed for %r: %s", row_id, exc)
            return
        action = action_obj["action"]
        normalized = row_id

        # Any SQL error inside this body aborts the connection's transaction in
        # Postgres; without an explicit ROLLBACK the next on_result call hits
        # InFailedSqlTransaction and the rest of the chunk is lost.
        try:
            if action == "chose":
                node_id = int(action_obj["node_id"])
                if not _node_exists(conn, node_id):
                    log.warning(
                        "LLM chose node_id=%d which is not in taxonomy_nodes "
                        "for %r — abstaining (likely hallucination)",
                        node_id, normalized,
                    )
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    return
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=node_id,
                    source="llm", mapper_version=MAPPER_VERSION,
                )
            elif action == "propose_brand":
                node_kind = action_obj.get("node_kind")
                if node_kind not in _VALID_NODE_KINDS:
                    log.warning(
                        "LLM proposed invalid node_kind=%r for %r "
                        "(must be 'brand' or 'expression') — abstaining",
                        node_kind, normalized,
                    )
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    return
                cands = _candidates_with_parents(conn, normalized)
                parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
                if parent_id is None:
                    write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                    return
                new_id = _create_brand_node(
                    conn,
                    slug=action_obj["slug"],
                    display_name=action_obj["display_name"],
                    parent_id=parent_id,
                    node_kind=node_kind,
                    raw_string=normalized,
                    prompt_hash_value=prompt_hash(normalized, None, None, cands),
                    model_id=provider.model_id,
                )
                write_resolution(
                    conn, normalized_name=normalized, taxonomy_node_id=new_id,
                    source="llm", mapper_version=MAPPER_VERSION,
                )
            elif action == "propose_form":
                cands = _candidates_with_parents(conn, normalized)
                parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
                enqueue_form_proposal(
                    conn,
                    raw_string=normalized,
                    proposed_slug=action_obj["slug"],
                    proposed_display_name=action_obj["display_name"],
                    proposed_parent_id=parent_id,
                    candidates=cands,
                    mapper_version=MAPPER_VERSION,
                )
            elif action == "abstain":
                write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
        except Exception:
            conn.rollback()
            raise

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="mapping.resolve_pending",
        version_constant=MAPPER_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )
