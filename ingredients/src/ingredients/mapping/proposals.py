"""CRUD over taxonomy_proposals (form-node review queue).

Brand/expression auto-creates do NOT use this table — they go straight
into taxonomy_nodes with a taxonomy_provenance row.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

_VALID_STATUSES = {"pending", "approved", "rejected"}


def enqueue_form_proposal(
    conn: psycopg.Connection,
    *,
    raw_string: str,
    proposed_slug: str,
    proposed_display_name: str,
    proposed_parent_id: int | None,
    candidates: list[dict[str, Any]],
    mapper_version: str,
) -> int:
    """Insert if (raw_string, mapper_version) absent; return existing id otherwise."""
    row = conn.execute(
        """
        insert into taxonomy_proposals
            (raw_string, proposed_slug, proposed_display_name, proposed_parent_id,
             candidates, mapper_version)
        values (%s, %s, %s, %s, %s::jsonb, %s)
        on conflict (raw_string, mapper_version) do update
            set proposed_slug = excluded.proposed_slug,
                proposed_display_name = excluded.proposed_display_name
        returning id
        """,
        (raw_string, proposed_slug, proposed_display_name, proposed_parent_id,
         json.dumps(candidates), mapper_version),
    ).fetchone()
    conn.commit()
    return row[0]


def fetch_pending_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, raw_string, proposed_slug, proposed_parent_id, candidates,
               mapper_version, proposed_display_name
        from taxonomy_proposals
        where status = 'pending'
        order by created_at, id
        """
    ).fetchall()
    return [
        {
            "id": r[0], "raw_string": r[1], "proposed_slug": r[2],
            "proposed_parent_id": r[3], "candidates": r[4], "mapper_version": r[5],
            "proposed_display_name": r[6],
        }
        for r in rows
    ]


def mark_decided(
    conn: psycopg.Connection, *,
    proposal_id: int, status: str, decided_by: str,
) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {_VALID_STATUSES}")
    conn.execute(
        "update taxonomy_proposals "
        "set status = %s, decided_by = %s, decided_at = now() where id = %s",
        (status, decided_by, proposal_id),
    )
    conn.commit()


def approve_form_proposal(
    conn: psycopg.Connection,
    *,
    proposal: dict[str, Any],
    decided_by: str,
    version: str,
) -> int:
    """Approve a form proposal: create the node + edge + alias, resolve the name.

    Mirrors the brand auto-create for the human-reviewed case. Requires a parent
    (a form node without one can't be attached) — raises if absent. The raw
    string becomes an alias of the new node and the shared resolution points the
    name at the new slug, so every recipe that uses it now maps. Returns the new
    node id.
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
    mark_decided(conn, proposal_id=proposal["id"], status="approved", decided_by=decided_by)
    return new_id
