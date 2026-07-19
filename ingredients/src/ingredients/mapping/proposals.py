"""Human review of map *form* proposals.

The map LLM tier can't auto-create a new substance *form* node (e.g. "lemon
zest"), so it writes an open `human_reviews` row (stage='map',
origin='machine_proposal', payload.kind='form') and parks the name. A curator
approves it here: create the node + edge + alias + shared resolution, then mark
the review resolved. (Enqueuing is now `reviews.model.insert_review`, done by the
map LLM tier; this module is the read + approve side.)
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.reviews import model


def fetch_pending_form_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Open map form-proposal reviews, oldest first."""
    rows = conn.execute(
        """
        select id, entity_id, payload
        from human_reviews
        where stage = 'map' and origin = 'machine_proposal' and state = 'open'
          and payload->>'kind' = 'form'
        order by created_at, id
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "raw_string": r[1],
            "proposed_slug": (r[2] or {}).get("proposed_slug"),
            "proposed_display_name": (r[2] or {}).get("proposed_display_name"),
            "proposed_parent_id": (r[2] or {}).get("proposed_parent_id"),
            "candidates": (r[2] or {}).get("candidates") or [],
        }
        for r in rows
    ]


def approve_form_proposal(
    conn: psycopg.Connection,
    *,
    proposal: dict[str, Any],
    decided_by: str,
    version: str,
) -> int:
    """Approve a form proposal: create the node + edge + alias, resolve the name,
    and mark the review resolved. Requires a parent (a form node without one can't
    be attached) — raises if absent. The raw string becomes an alias of the new
    node and the shared resolution points the name at the new slug, so every
    recipe that uses it now maps. Returns the new node id.
    """
    from ingredients.mapping.resolutions import write_resolution

    parent_id = proposal.get("proposed_parent_id")
    if not parent_id:
        raise ValueError("cannot approve a form proposal without a parent")

    slug = proposal["proposed_slug"]
    display_name = proposal.get("proposed_display_name") or slug.replace("-", " ").title()
    raw_string = proposal["raw_string"]

    new_id = conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
        (slug, display_name),
    ).fetchone()[0]
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (parent_id, new_id),
    )
    conn.execute(
        "insert into taxonomy_aliases (alias, node_id) values (%s, %s) on conflict do nothing",
        (raw_string, new_id),
    )
    write_resolution(
        conn,
        normalized_name=raw_string,
        taxonomy_slug=slug,
        method="manual",
        version=version,
    )
    model.set_state(conn, proposal["id"], "resolved", reviewed_by=decided_by)
    return new_id
