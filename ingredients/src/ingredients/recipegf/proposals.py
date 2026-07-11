"""CRUD over ``recipegf_proposals`` — the review queue for drinks the
deterministic converter couldn't emit as a bundle.

Mirrors ``ingredients.mapping.proposals``: idempotent enqueue keyed on
``(cluster_id, converter_version)``, a pending-fetch for the interactive
reviewer, and a decision writer. Resolving a proposal is out-of-band (fix the
taxonomy/data or teach the converter, then re-export) — approval here just
records the human's disposition; unlike taxonomy_proposals it does not itself
create a bundle.
"""

from __future__ import annotations

from typing import Any

import psycopg

_VALID_STATUSES = {"pending", "resolved", "rejected"}


def enqueue_proposal(
    conn: psycopg.Connection,
    *,
    cluster_id: int,
    canonical_name: str,
    proposed_slug: str | None,
    reason: str,
    detail: str,
    source_url: str | None,
    converter_version: str,
) -> int:
    """Insert if ``(cluster_id, converter_version)`` absent; refresh reason/
    detail otherwise. Returns the proposal id. Caller commits."""
    row = conn.execute(
        """
        insert into recipegf_proposals
            (cluster_id, canonical_name, proposed_slug, reason, detail,
             source_url, converter_version)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (cluster_id, converter_version) do update
            set reason = excluded.reason,
                detail = excluded.detail,
                proposed_slug = excluded.proposed_slug,
                canonical_name = excluded.canonical_name,
                status = 'pending'
        returning id
        """,
        (cluster_id, canonical_name, proposed_slug, reason, detail,
         source_url, converter_version),
    ).fetchone()
    return row[0]


def fetch_pending_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, cluster_id, canonical_name, proposed_slug, reason, detail,
               source_url, converter_version
        from recipegf_proposals
        where status = 'pending'
        order by reason, created_at, id
        """
    ).fetchall()
    return [
        {
            "id": r[0], "cluster_id": r[1], "canonical_name": r[2],
            "proposed_slug": r[3], "reason": r[4], "detail": r[5],
            "source_url": r[6], "converter_version": r[7],
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
        "update recipegf_proposals "
        "set status = %s, decided_by = %s, decided_at = now() where id = %s",
        (status, decided_by, proposal_id),
    )
    conn.commit()
