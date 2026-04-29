"""Phase 2 orchestrator. Drains the pending_llm queue using a chosen provider.

Branching by LLM action:

  chose          -> write_resolution(source='llm')
  propose_brand  -> insert taxonomy_node + edge + provenance, then resolve
  propose_form   -> enqueue_form_proposal; row stays pending_llm for review
  abstain        -> write_abstain
"""

from __future__ import annotations

import logging
import time
from collections import Counter

import psycopg

from .db import fetch_pending_llm_names, write_abstain, write_resolution
from .lexical_layer import lexical_candidates
from .llm_provider import LLMProvider
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


def _create_brand_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    display_name: str,
    parent_id: int,
    role: str,
    raw_string: str,
    prompt_hash_value: str,
    model_id: str,
) -> int:
    """Insert the new node + edge + provenance. is_cluster_node defaults
    to false (E's column); the antichain stays curator-controlled."""
    new_id = conn.execute(
        "insert into taxonomy_nodes (slug, display_name, role) "
        "values (%s, %s, %s) returning id",
        (slug, display_name, role),
    ).fetchone()[0]
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (parent_id, new_id),
    )
    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, prompt_hash, model_id)
        values (%s, 'llm-mapper', %s, %s, %s, %s)
        """,
        (new_id, MAPPER_VERSION, raw_string, prompt_hash_value, model_id),
    )
    # NOTE: no conn.commit() here — the caller's write_resolution() commit
    # covers the whole unit (node + edge + provenance + row update) atomically.
    return new_id


def _resolve_with_retry(
    provider: LLMProvider, *, system_prompt: str, user_prompt: str,
    normalized_name: str, max_attempts: int = 3,
) -> dict | None:
    """Call provider + parse; retry on any exception with exponential backoff.
    Returns the parsed action dict, or None if all attempts failed."""
    for attempt in range(max_attempts):
        try:
            raw = provider.resolve(
                system_prompt=system_prompt, user_prompt=user_prompt,
            ).raw_text
            return parse_response(raw)
        except Exception as exc:
            if attempt + 1 == max_attempts:
                log.error(
                    "LLM call exhausted retries for %r: %s",
                    normalized_name, exc,
                )
                return None
            sleep_for = 2 ** attempt   # 1s, 2s, 4s
            log.warning(
                "LLM call failed for %r (attempt %d/%d): %s — retrying in %ds",
                normalized_name, attempt + 1, max_attempts, exc, sleep_for,
            )
            time.sleep(sleep_for)
    return None


# Public re-export so other stages (e.g. dedup) can reuse the retry helper
# without depending on the orchestrator details.
resolve_with_retry = _resolve_with_retry


def run_phase2(
    conn: psycopg.Connection,
    *,
    provider: LLMProvider,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Drain the pending_llm queue. Returns Counter-shaped summary keyed by action."""
    counts: Counter[str] = Counter()
    names = fetch_pending_llm_names(conn, mapper_version=MAPPER_VERSION, limit=limit)
    for normalized in names:
        cands = _candidates_with_parents(conn, normalized)
        user_prompt = build_user_prompt(
            normalized_name=normalized, parser_unit=None, site=site, candidates=cands,
        )
        action_obj = _resolve_with_retry(
            provider,
            system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
            normalized_name=normalized,
        )
        if action_obj is None:
            # All retries exhausted; leave row at pending_llm and move on.
            counts["error"] += 1
            continue
        action = action_obj["action"]

        if action == "chose":
            write_resolution(
                conn, normalized_name=normalized,
                taxonomy_node_id=int(action_obj["node_id"]),
                source="llm", mapper_version=MAPPER_VERSION,
            )
            counts["chose"] += 1
        elif action == "propose_brand":
            parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
            if parent_id is None:
                write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                counts["abstain"] += 1
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
                    role=action_obj["role"],
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
    return dict(counts)
