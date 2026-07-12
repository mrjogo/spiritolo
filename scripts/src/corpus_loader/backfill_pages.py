"""One-time backfill: set ``pages.r2_key`` for every row that lacks one.

Run once after the corpus loader has uploaded the pre-staged HTML cache
(so every url in ``pages`` has a matching R2 object keyed the same way —
see keys.sha256_key / load.load). Idempotent: rows that already have an
r2_key are left untouched.
"""
from __future__ import annotations

from typing import Protocol

from .keys import sha256_key


class Executable(Protocol):
    """The subset of a DB-API-ish connection this needs (psycopg3's
    ``conn.execute(sql, params)`` shorthand, or a test double)."""

    def execute(self, sql: str, params: object = ()) -> object: ...


def backfill_pages(conn: Executable) -> int:
    """Set ``r2_key = sha256(url)`` on every ``pages`` row missing one.

    Returns the number of rows updated. Only ``r2_key`` is touched; every
    other column on every row is left exactly as-is.
    """
    rows = conn.execute(
        "select id, url from pages where r2_key is null"
    ).fetchall()
    for row_id, url in rows:
        conn.execute(
            "update pages set r2_key = %s where id = %s",
            (sha256_key(url), row_id),
        )
    return len(rows)
