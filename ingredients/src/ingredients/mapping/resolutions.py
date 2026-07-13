"""Writes into the shared, name-keyed `ingredient_resolutions` table.

Resolution is keyed by normalized ingredient name, not per recipe row: one row
per name re-points every recipe that uses it. `taxonomy_slug` null records a
deliberate abstain (name seen, no confident node), which the map stage's queue
reads as "tried, abstained" rather than "never tried". Every tier (alias,
lexical, LLM) funnels its write through here so the UPSERT semantics stay in one
place.
"""

from __future__ import annotations

import psycopg


def write_resolution(
    conn: psycopg.Connection,
    *,
    normalized_name: str,
    taxonomy_slug: str | None,
    method: str,
    version: str,
    model_id: str | None = None,
    confidence: float | None = None,
) -> None:
    """UPSERT the resolution for `normalized_name` to `taxonomy_slug`."""
    conn.execute(
        """
        insert into ingredient_resolutions
            (normalized_name, taxonomy_slug, method, version, model_id, confidence)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (normalized_name) do update set
            taxonomy_slug = excluded.taxonomy_slug,
            method        = excluded.method,
            version       = excluded.version,
            model_id      = excluded.model_id,
            confidence    = excluded.confidence,
            updated_at    = now()
        """,
        (normalized_name, taxonomy_slug, method, version, model_id, confidence),
    )


def write_abstain(
    conn: psycopg.Connection, *, normalized_name: str, version: str
) -> None:
    """Record that a name was seen but no confident node was found."""
    write_resolution(
        conn,
        normalized_name=normalized_name,
        taxonomy_slug=None,
        method="abstain",
        version=version,
    )
