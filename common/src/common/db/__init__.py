"""The shared SQLite data layer.

One file, one writer, WAL mode. ``open_database`` returns a :class:`Connection`
whose surface mirrors the small subset of psycopg the pipeline code was written
against (``execute`` / ``executemany`` / ``cursor()`` / ``transaction()`` /
``commit`` / ``rollback``), so stage code reads the same whether it runs inside
the API process, the CLI, or a test. Schema lives in ``migrations/*.sql`` and is
applied at open; the audit log is written by per-connection triggers that read
the actor from a per-connection context (see :mod:`common.db.audit`).
"""

from .connection import (
    Connection,
    Row,
    SQL_NOW,
    DatabaseError,
    IntegrityError,
    jdump,
    jload,
    jlist,
    now_iso,
    open_database,
    open_memory_database,
)

__all__ = [
    "Connection",
    "Row",
    "SQL_NOW",
    "DatabaseError",
    "IntegrityError",
    "jdump",
    "jload",
    "jlist",
    "now_iso",
    "open_database",
    "open_memory_database",
]
