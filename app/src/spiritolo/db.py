"""Per-thread SQLite connections for request handling.

Sync FastAPI endpoints run on a thread pool, and a ``sqlite3`` connection must
not be shared across threads mid-statement, so each worker thread lazily opens
its own :class:`common.db.Connection` to the one database file. Migrations run
exactly once, at boot, on the first connection; the per-thread ones skip them.
The audit actor is reset per request (``set_actor``) so writes carry the
operator's identity.
"""

from __future__ import annotations

import threading

from common.db import Connection, open_database
from common.db.audit import set_actor


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()
        self._all: list[Connection] = []
        self._lock = threading.Lock()
        # Bumped by reopen(); a thread whose cached connection predates the
        # current generation opens a new one (the old was closed under it).
        self._generation = 0
        self.migrate()

    def migrate(self) -> None:
        """Apply pending migrations synchronously, before anything else
        touches the file (boot, and again after an import swap)."""
        boot = open_database(self.path, migrate=True, audit=False)
        boot.close()

    def connection(self) -> Connection:
        cached = getattr(self._local, "conn", None)
        if cached is not None and cached[0] == self._generation:
            return cached[1]
        conn = open_database(self.path, migrate=False, audit=True,
                             actor=("system", None, "api"))
        self._local.conn = (self._generation, conn)
        with self._lock:
            self._all.append(conn)
        return conn

    def new_connection(self, *, actor: tuple[str, str | None, str]) -> Connection:
        """A dedicated connection (the executor thread owns one)."""
        return open_database(self.path, migrate=False, audit=True, actor=actor)

    def close_all(self) -> None:
        with self._lock:
            conns, self._all = self._all, []
            self._generation += 1
        for c in conns:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def reopen(self) -> None:
        """After the file on disk was replaced: drop every cached connection
        and migrate the new file. Threads reconnect lazily."""
        self.close_all()
        self.migrate()


def as_actor(conn: Connection, operator_id: int | None, source: str) -> None:
    if operator_id is None:
        set_actor(conn, "system", None, source)
    else:
        set_actor(conn, "human", str(operator_id), source)
