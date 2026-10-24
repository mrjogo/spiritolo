"""Curator-facing review operations (port of ``flag_review`` /
``resolve_review``). The ops API calls these with the operator's identity."""

from __future__ import annotations

from typing import Any

from common.db import SQL_NOW, Connection, jdump

from ingredients.reviews.apply import apply_review


def flag_review(conn: Connection, *, entity_kind: str, entity_id: str, stage: str,
                note: str | None = None, created_by: str | None = None) -> int:
    """Open (or annotate the already-open) human flag for an entity."""
    row = conn.execute(
        f"""
        insert into human_reviews (entity_kind, entity_id, stage, origin, note, created_by)
        values (?, ?, ?, 'human_flag', ?, ?)
        on conflict (entity_kind, entity_id, stage) where state = 'open'
          do update set note = coalesce(excluded.note, human_reviews.note),
                        updated_at = {SQL_NOW}
        returning id
        """,
        (entity_kind, entity_id, stage, note, created_by),
    ).fetchone()
    return row[0]


def resolve_review(conn: Connection, review_id: int, *, payload: Any | None = None,
                   dismiss: bool = False, reviewed_by: str | None = None) -> None:
    """Dismiss, or resolve (optionally replacing the payload) and apply."""
    if dismiss:
        conn.execute(
            f"update human_reviews set state = 'dismissed', reviewed_by = ?, "
            f"reviewed_at = {SQL_NOW}, updated_at = {SQL_NOW} where id = ?",
            (reviewed_by, review_id),
        )
        return
    with conn.transaction():
        conn.execute(
            f"update human_reviews set state = 'resolved', payload = coalesce(?, payload), "
            f"reviewed_by = ?, reviewed_at = {SQL_NOW}, updated_at = {SQL_NOW} where id = ?",
            (jdump(payload), reviewed_by, review_id),
        )
        apply_review(conn, review_id)
