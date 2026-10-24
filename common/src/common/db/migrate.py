"""Plain-SQL migrations applied at open, tracked in ``schema_migrations``.

Files live in ``common/db/migrations/NNNN_name.sql`` and apply in filename
order, each inside one transaction. There is no down direction: write a new
forward migration. The runner is idempotent and cheap, so every process (API,
CLI, tests) just calls it at startup — no separate deploy step, no CI job, no
vendor CLI.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from .connection import Connection

_LEDGER_DDL = """
create table if not exists schema_migrations (
    filename   text primary key,
    applied_at text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""


def migration_files() -> list[tuple[str, str]]:
    """``(filename, sql)`` for every bundled migration, sorted by filename."""
    root = resources.files(__package__) / "migrations"
    out: list[tuple[str, str]] = []
    for entry in root.iterdir():
        if entry.name.endswith(".sql"):
            out.append((entry.name, entry.read_text(encoding="utf-8")))
    out.sort(key=lambda t: t[0])
    return out


def applied(conn: Connection) -> set[str]:
    conn.execute(_LEDGER_DDL)
    return {r[0] for r in conn.execute("select filename from schema_migrations").fetchall()}


def apply_pending(conn: Connection) -> list[str]:
    """Apply every migration not yet recorded; return the filenames applied."""
    done = applied(conn)
    newly: list[str] = []
    for name, sql in migration_files():
        if name in done:
            continue
        # executescript commits any open transaction and runs the script
        # statement by statement; wrap it so a failing migration leaves no
        # half-applied schema behind.
        conn.raw.execute("begin")
        try:
            for statement in _split(sql):
                conn.raw.execute(statement)
            conn.raw.execute(
                "insert into schema_migrations (filename) values (?)", (name,)
            )
            conn.raw.execute("commit")
        except BaseException:
            conn.raw.execute("rollback")
            raise
        newly.append(name)
    return newly


def _split(sql: str) -> list[str]:
    """Split a migration into statements, honouring trigger bodies (whose
    ``BEGIN ... END`` contains semicolons) via ``sqlite3.complete_statement``."""
    statements: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(";") and sqlite3.complete_statement("\n".join(buf)):
            statements.append("\n".join(buf))
            buf = []
    rest = "\n".join(buf).strip()
    if rest:
        statements.append(rest)
    return statements


def migrations_dir() -> Path:
    return Path(str(resources.files(__package__) / "migrations"))
