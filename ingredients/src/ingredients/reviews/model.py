"""Row access over `human_reviews`.

Keyed by `(entity_kind, entity_id, stage)` with at most one *open* row (a partial
unique index); resolved/dismissed rows accumulate as history. `entity_id` is
text so one table holds both bigint ids (as text) and map's name-keys.
"""

from __future__ import annotations

from typing import Any, Iterable

from psycopg.types.json import Json


def insert_review(
    conn,
    *,
    entity_kind: str,
    entity_id: str,
    stage: str,
    origin: str,
    payload: Any | None = None,
    note: str | None = None,
    origin_version: str | None = None,
    state: str = "open",
    created_by: str | None = None,
) -> int:
    """Insert a review; return its id.

    Respects the one-open constraint: inserting a second *open* review for the
    same `(entity_kind, entity_id, stage)` is a no-op that returns the existing
    open row's id. Resolved/dismissed inserts (e.g. backfill) always insert.
    """
    row = conn.execute(
        """
        insert into human_reviews
            (entity_kind, entity_id, stage, origin, payload, note,
             origin_version, state, created_by)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (entity_kind, entity_id, stage) where state = 'open'
            do nothing
        returning id
        """,
        (
            entity_kind, entity_id, stage, origin,
            Json(payload) if payload is not None else None,
            note, origin_version, state, created_by,
        ),
    ).fetchone()
    if row is not None:
        return row[0]
    existing = conn.execute(
        "select id from human_reviews "
        "where entity_kind = %s and entity_id = %s and stage = %s and state = 'open'",
        (entity_kind, entity_id, stage),
    ).fetchone()
    return existing[0]


def set_state(
    conn, review_id: int, state: str, reviewed_by: str | None = None
) -> None:
    """Move a review to `state` (resolved/dismissed/open), stamping the reviewer."""
    conn.execute(
        "update human_reviews set state = %s, reviewed_by = %s, reviewed_at = now() "
        "where id = %s",
        (state, reviewed_by, review_id),
    )


def open_reviews_for(
    conn, *, stage: str, entity_ids: Iterable[str]
) -> list[dict[str, Any]]:
    """Open reviews for `stage` whose entity_id is in `entity_ids`."""
    rows = conn.execute(
        "select id, entity_kind, entity_id, origin, payload, note "
        "from human_reviews "
        "where stage = %s and state = 'open' and entity_id = any(%s)",
        (stage, list(entity_ids)),
    ).fetchall()
    return [
        {"id": r[0], "entity_kind": r[1], "entity_id": r[2],
         "origin": r[3], "payload": r[4], "note": r[5]}
        for r in rows
    ]


def resolved_override_ids(
    conn, *, stage: str, ids: Iterable[str]
) -> list[int]:
    """Ids of resolved overrides for `stage` relevant to `ids`.

    Matches an override whose `entity_id` is exactly in `ids` (recipe-keyed:
    extract/convert/cluster; or name-keyed: map) OR whose `entity_id` prefix
    before ':' is in `ids` (parse's stable "recipe_id:position" key). So a caller
    passes recipe-id-strings (recipe stages) or names (map) and gets every
    override those entities own.
    """
    id_list = list(ids)
    if not id_list:
        return []
    rows = conn.execute(
        "select id from human_reviews "
        "where stage = %s and state = 'resolved' "
        "and (entity_id = any(%s) or split_part(entity_id, ':', 1) = any(%s))",
        (stage, id_list, id_list),
    ).fetchall()
    return [r[0] for r in rows]
