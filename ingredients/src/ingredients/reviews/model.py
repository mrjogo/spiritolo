"""Row access over `human_reviews`.

Keyed by `(entity_kind, entity_id, stage)` with at most one *open* row (a partial
unique index); resolved/dismissed rows accumulate as history. `entity_id` is
text so one table holds both integer ids (as text) and map's name-keys.
"""

from __future__ import annotations

from typing import Any, Iterable

from common.db import SQL_NOW, jdump, jlist, jload

# parse's entity key is "recipe_id:position"; every other stage keys by the bare
# entity id. This expression yields the part before the colon (or the whole id).
ENTITY_PREFIX_SQL = (
    "case when instr(entity_id, ':') > 0 "
    "then substr(entity_id, 1, instr(entity_id, ':') - 1) else entity_id end"
)


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
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict (entity_kind, entity_id, stage) where state = 'open'
            do nothing
        returning id
        """,
        (
            entity_kind, entity_id, stage, origin, jdump(payload),
            note, origin_version, state, created_by,
        ),
    ).fetchone()
    if row is not None:
        return row[0]
    existing = conn.execute(
        "select id from human_reviews "
        "where entity_kind = ? and entity_id = ? and stage = ? and state = 'open'",
        (entity_kind, entity_id, stage),
    ).fetchone()
    return existing[0]


def set_state(
    conn, review_id: int, state: str, reviewed_by: str | None = None
) -> None:
    """Move a review to `state` (resolved/dismissed/open), stamping the reviewer."""
    conn.execute(
        f"update human_reviews set state = ?, reviewed_by = ?, reviewed_at = {SQL_NOW}, "
        f"updated_at = {SQL_NOW} where id = ?",
        (state, reviewed_by, review_id),
    )


def open_reviews_for(
    conn, *, stage: str, entity_ids: Iterable[str]
) -> list[dict[str, Any]]:
    """Open reviews for `stage` whose entity_id is in `entity_ids`."""
    rows = conn.execute(
        "select id, entity_kind, entity_id, origin, payload, note "
        "from human_reviews "
        "where stage = ? and state = 'open' "
        "and entity_id in (select value from json_each(?))",
        (stage, jlist(entity_ids)),
    ).fetchall()
    return [
        {"id": r[0], "entity_kind": r[1], "entity_id": r[2],
         "origin": r[3], "payload": jload(r[4]), "note": r[5]}
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
    id_list = [str(i) for i in ids]
    if not id_list:
        return []
    rows = conn.execute(
        f"select id from human_reviews "
        f"where stage = ? and state = 'resolved' "
        f"and (entity_id in (select value from json_each(?)) "
        f"  or {ENTITY_PREFIX_SQL} in (select value from json_each(?)))",
        (stage, jlist(id_list), jlist(id_list)),
    ).fetchall()
    return [r[0] for r in rows]
