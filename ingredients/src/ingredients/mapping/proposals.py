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
            (raw_string, proposed_slug, proposed_parent_id, candidates, mapper_version)
        values (%s, %s, %s, %s::jsonb, %s)
        on conflict (raw_string, mapper_version) do update
            set proposed_slug = excluded.proposed_slug
        returning id
        """,
        (raw_string, proposed_slug, proposed_parent_id, json.dumps(candidates), mapper_version),
    ).fetchone()
    conn.commit()
    # The display_name isn't stored on the row (it's reconstructable from the
    # node when the proposal is approved); kept as a parameter for future use
    # by the review CLI without changing the schema. Suppress unused-arg warning.
    _ = proposed_display_name
    return row[0]


def fetch_pending_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, raw_string, proposed_slug, proposed_parent_id, candidates, mapper_version
        from taxonomy_proposals
        where status = 'pending'
        order by created_at, id
        """
    ).fetchall()
    return [
        {
            "id": r[0], "raw_string": r[1], "proposed_slug": r[2],
            "proposed_parent_id": r[3], "candidates": r[4], "mapper_version": r[5],
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
