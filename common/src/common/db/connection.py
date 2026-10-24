"""SQLite connection wrapper with a psycopg-shaped surface.

Why a wrapper at all: the pipeline stages were written against psycopg's
``conn.execute(...).fetchall()`` / ``with conn.transaction():`` /
``with conn.cursor() as cur: cur.executemany(...)`` idioms. Keeping that shape
means the port is a change of SQL dialect, not of control flow, and the stage
code stays readable. The wrapper adds three things SQLite's stdlib module lacks:

- **Nested transactions.** ``transaction()`` opens ``BEGIN IMMEDIATE`` at depth
  0 and a ``SAVEPOINT`` below that, so a stage can wrap a risky call in its own
  ``with conn.transaction():`` inside a chunk transaction and have only that
  block roll back on error (the connect stage relies on this).
- **Autocommit semantics.** Outside an explicit transaction every statement
  commits on its own (``isolation_level=None``), matching the autocommit
  connections the worker and CLI used.
- **JSON / array helpers.** Postgres gave the code ``jsonb`` → ``dict`` and
  ``text[]`` → ``list`` for free. SQLite stores both as JSON text; ``jload`` /
  ``jdump`` / ``jlist`` are the explicit boundary.

Timestamps are ISO-8601 UTC text (``2026-10-22T23:45:00.123Z``) produced by
``now_iso()`` in Python and by ``strftime('%Y-%m-%dT%H:%M:%fZ','now')`` in SQL
defaults, so they sort lexically and compare correctly across both sides.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError

# SQL expression for "now" in the same text format now_iso() produces.
SQL_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


class Row(tuple):
    """A result row: a plain ``tuple`` (so ``row == ("a", 1)`` and unpacking
    work as before) that also answers to column names (``row["slug"]``)."""

    def __new__(cls, cols: dict[str, int], values: Iterable[Any]) -> "Row":
        self = tuple.__new__(cls, values)
        self._cols = cols
        return self

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, str):
            return tuple.__getitem__(self, self._cols[key])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._cols)

    def get(self, key: str, default: Any = None) -> Any:
        idx = self._cols.get(key)
        return default if idx is None else tuple.__getitem__(self, idx)

    def asdict(self) -> dict[str, Any]:
        return {k: tuple.__getitem__(self, i) for k, i in self._cols.items()}


_COLMAP_CACHE: dict[tuple, dict[str, int]] = {}


def _row_factory(cursor: sqlite3.Cursor, values: tuple) -> Row:
    desc = cursor.description
    cols = _COLMAP_CACHE.get(desc)
    if cols is None:
        cols = {d[0]: i for i, d in enumerate(desc)}
        if len(_COLMAP_CACHE) > 4096:
            _COLMAP_CACHE.clear()
        _COLMAP_CACHE[desc] = cols
    return Row(cols, values)


def now_iso() -> str:
    """Current UTC time as ISO-8601 text with millisecond precision + ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def jdump(value: Any) -> str | None:
    """Serialize ``value`` for a JSON text column (``None`` stays SQL NULL)."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def jload(text: Any, default: Any = None) -> Any:
    """Parse a JSON text column; ``None`` (or '') returns ``default``. A value
    that is already a dict/list is returned unchanged so callers can be lenient
    about whether a row came straight from SQLite or was built in Python."""
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return json.loads(text)


def jlist(values: Iterable[Any] | None) -> str:
    """Serialize a sequence for an ``IN (select value from json_each(?))``
    parameter or an array column. ``None`` becomes ``'[]'``."""
    return json.dumps(list(values) if values is not None else [], ensure_ascii=False)


class Cursor:
    """A thin wrapper over ``sqlite3.Cursor`` that is also a context manager,
    so ``with conn.cursor() as cur:`` reads as it did under psycopg."""

    def __init__(self, raw: sqlite3.Cursor) -> None:
        self._raw = raw

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        self._raw.close()

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> "Cursor":
        self._raw.execute(sql, params)
        return self

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> "Cursor":
        self._raw.executemany(sql, seq)
        return self

    def fetchone(self) -> Any:
        return self._raw.fetchone()

    def fetchall(self) -> list[Any]:
        return self._raw.fetchall()

    def __iter__(self):
        return iter(self._raw)

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._raw.lastrowid

    @property
    def description(self):
        return self._raw.description


class Connection:
    """psycopg-shaped wrapper over one ``sqlite3.Connection``.

    Rows come back as ``sqlite3.Row`` (indexable by position AND by column
    name), which satisfies both the ``r[0]`` style the stages use and the
    ``row["col"]`` style the API prefers.
    """

    def __init__(self, raw: sqlite3.Connection, *, path: str) -> None:
        self._raw = raw
        self._depth = 0
        self.path = path
        # Mirrors psycopg's attribute; the loop code checks it before committing.
        # Statements outside ``transaction()`` always autocommit here.
        self.autocommit = True

    # -- statements ---------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Cursor:
        return Cursor(self._raw.execute(sql, params))

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> Cursor:
        return Cursor(self._raw.executemany(sql, seq))

    def executescript(self, sql: str) -> None:
        self._raw.executescript(sql)

    def cursor(self) -> Cursor:
        return Cursor(self._raw.cursor())

    # -- transactions -------------------------------------------------------

    @property
    def in_transaction(self) -> bool:
        return self._raw.in_transaction

    @contextmanager
    def transaction(self):
        """Nested-transaction context: ``BEGIN IMMEDIATE`` at the outermost
        level, ``SAVEPOINT`` inside. Commits/releases on success, rolls back the
        innermost scope on exception (and re-raises)."""
        if self._depth == 0 and not self._raw.in_transaction:
            self._raw.execute("begin immediate")
            self._depth = 1
            try:
                yield self
            except BaseException:
                self._raw.execute("rollback")
                raise
            else:
                self._raw.execute("commit")
            finally:
                self._depth = 0
        else:
            self._depth += 1
            name = f"sp_{self._depth}"
            self._raw.execute(f"savepoint {name}")
            try:
                yield self
            except BaseException:
                self._raw.execute(f"rollback to {name}")
                self._raw.execute(f"release {name}")
                raise
            else:
                self._raw.execute(f"release {name}")
            finally:
                self._depth -= 1

    def commit(self) -> None:
        """Commit an open implicit transaction; a no-op when none is open (the
        common case, since statements autocommit)."""
        if self._raw.in_transaction and self._depth == 0:
            self._raw.execute("commit")

    def rollback(self) -> None:
        if self._raw.in_transaction and self._depth == 0:
            self._raw.execute("rollback")

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._raw.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def raw(self) -> sqlite3.Connection:
        return self._raw


# Declared-type converters (``detect_types=PARSE_DECLTYPES``): a column declared
# ``JSONTEXT`` comes back parsed (dict/list), a ``BOOLEAN`` as ``bool`` — the
# same shapes psycopg handed the pipeline for ``jsonb`` / ``boolean``. Only
# applies to direct column reads; an expression over a JSON column still
# returns text, which ``jload`` accepts either way.
sqlite3.register_converter("JSONTEXT", lambda b: json.loads(b.decode("utf-8")) if b else None)
sqlite3.register_converter("BOOLEAN", lambda b: b not in (b"0", b"", b"0.0"))


def _configure(raw: sqlite3.Connection, *, wal: bool) -> None:
    raw.row_factory = _row_factory
    raw.execute("pragma foreign_keys = on")
    raw.execute("pragma busy_timeout = 30000")
    if wal:
        raw.execute("pragma journal_mode = wal")
        raw.execute("pragma synchronous = normal")
    raw.execute("pragma temp_store = memory")


def open_database(
    path: str | os.PathLike[str],
    *,
    migrate: bool = True,
    audit: bool = True,
    actor: tuple[str, str | None, str] = ("system", None, "unknown"),
) -> Connection:
    """Open (and create) the database at ``path``.

    ``migrate`` applies any pending ``migrations/*.sql`` (tracked in
    ``schema_migrations``). ``audit`` installs the per-connection audit
    triggers; pass ``False`` only for bulk loads that copy an audit log in
    (the ETL), never for application writes. ``actor`` seeds the connection's
    audit context (``kind, id, source``); change it per unit of work with
    :func:`common.db.audit.set_actor`.
    """
    from . import audit as _audit
    from . import migrate as _migrate

    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(
        str(p), isolation_level=None, check_same_thread=False,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    _configure(raw, wal=str(p) != ":memory:")
    conn = Connection(raw, path=str(p))
    if migrate:
        _migrate.apply_pending(conn)
    if audit:
        _audit.install(conn, actor=actor)
    return conn


def open_memory_database(*, audit: bool = True) -> Connection:
    """A fresh in-memory database with the full schema (tests)."""
    return open_database(":memory:", migrate=True, audit=audit)
