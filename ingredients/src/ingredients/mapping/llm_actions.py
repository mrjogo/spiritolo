"""Apply an LLM tier's per-name answer to the shared name-keyed resolution.

The deterministic tiers (alias, lexical) resolve a name straight to a taxonomy
slug. The LLM tier answers with a richer action, and this module is the single
place those actions turn into DB writes:

  chose_slug     -> write the resolution to an existing slug
  propose_brand  -> auto-create the brand/expression node + edge + provenance
                    (only when its parent slug already exists), then resolve
  propose_form   -> queue a taxonomy_proposals row for human review; the name is
                    left parked (no resolution) until a curator approves it
  abstain        -> record a deliberate abstain

The chain-answer contract per name is one of:
  - a bare slug string                                     -> chose that slug
  - {"action": "chose_slug", "slug": <str>}
  - {"action": "propose_brand", "slug", "display_name",
       "parent_slug", "node_kind"}
  - {"action": "propose_form", "slug", "display_name", "parent_slug"}
  - {"action": "abstain"}  (or None when the tier dropped the name)

A brand auto-create is atomic with its resolution write: node, edge, provenance,
and the resolution row land together, so a failed resolution never leaks an
orphan taxonomy node.
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.mapping.resolutions import write_abstain, write_resolution
from ingredients.reviews.model import insert_review

# taxonomy_nodes.node_kind has a CHECK constraint allowing only these values
# (plus NULL). An LLM-proposed brand/expression must validate before INSERT or
# the whole transaction aborts.
_VALID_NODE_KINDS = {"brand", "expression"}


def _lookup_node_by_slug(conn: psycopg.Connection, slug: str | None) -> int | None:
    if not slug:
        return None
    row = conn.execute(
        "select id from taxonomy_nodes where slug = %s", (slug,)
    ).fetchone()
    return row[0] if row else None


def auto_create_brand_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    display_name: str,
    parent_id: int,
    node_kind: str,
    raw_string: str,
    version: str,
    model_id: str | None = None,
    prompt_hash: str | None = None,
) -> int:
    """Insert the node + edge + provenance, returning the node id.

    `is_cluster_node` stays false — the antichain is curator-controlled, so an
    auto-created node is never promoted into it. Slug collisions (two answers
    proposing the same slug) resolve silently to the existing node; the edge and
    provenance inserts tolerate duplicates so re-encountering the same pair is
    idempotent.
    """
    row = conn.execute(
        "insert into taxonomy_nodes (slug, display_name, node_kind, is_cluster_node) "
        "values (%s, %s, %s, false) "
        "on conflict (slug) do nothing returning id",
        (slug, display_name, node_kind),
    ).fetchone()
    if row is None:
        new_id = conn.execute(
            "select id from taxonomy_nodes where slug = %s", (slug,)
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
        (new_id, version, raw_string, prompt_hash, model_id),
    )
    return new_id


def apply_llm_action(
    conn: psycopg.Connection,
    *,
    normalized_name: str,
    answer: Any,
    version: str,
    model_id: str | None = None,
) -> str:
    """Apply one name's LLM answer to the DB; return the action taken.

    Return values: ``chose`` | ``propose_brand`` | ``propose_form`` |
    ``abstain``. A ``propose_form`` leaves the name parked (no resolution row)
    so the recipe stays pending until a curator approves the proposal.
    """
    if answer is None:
        write_abstain(conn, normalized_name=normalized_name, version=version)
        return "abstain"

    if isinstance(answer, str):
        write_resolution(
            conn,
            normalized_name=normalized_name,
            taxonomy_slug=answer,
            method="llm",
            version=version,
            model_id=model_id,
        )
        return "chose"

    action = answer.get("action")

    if action == "chose_slug":
        slug = answer.get("slug")
        if not slug:
            write_abstain(conn, normalized_name=normalized_name, version=version)
            return "abstain"
        write_resolution(
            conn,
            normalized_name=normalized_name,
            taxonomy_slug=slug,
            method="llm",
            version=version,
            model_id=model_id,
        )
        return "chose"

    if action == "propose_brand":
        node_kind = answer.get("node_kind")
        parent_id = _lookup_node_by_slug(conn, answer.get("parent_slug"))
        if node_kind not in _VALID_NODE_KINDS or parent_id is None:
            write_abstain(conn, normalized_name=normalized_name, version=version)
            return "abstain"
        new_id = auto_create_brand_node(
            conn,
            slug=answer["slug"],
            display_name=answer["display_name"],
            parent_id=parent_id,
            node_kind=node_kind,
            raw_string=normalized_name,
            version=version,
            model_id=model_id,
        )
        slug = conn.execute(
            "select slug from taxonomy_nodes where id = %s", (new_id,)
        ).fetchone()[0]
        write_resolution(
            conn,
            normalized_name=normalized_name,
            taxonomy_slug=slug,
            method="llm",
            version=version,
            model_id=model_id,
        )
        return "propose_brand"

    if action == "propose_form":
        parent_id = _lookup_node_by_slug(conn, answer.get("parent_slug"))
        insert_review(
            conn,
            entity_kind="ingredient_name",
            entity_id=normalized_name,
            stage="map",
            origin="machine_proposal",
            payload={
                "kind": "form",
                "proposed_slug": answer["slug"],
                "proposed_display_name": answer["display_name"],
                "proposed_parent_id": parent_id,
                "candidates": answer.get("candidates") or [],
            },
            origin_version=version,
        )
        # Parked: no resolution row, so the recipe stays pending for review.
        return "propose_form"

    write_abstain(conn, normalized_name=normalized_name, version=version)
    return "abstain"
