"""Replace the live database with an uploaded SQLite file (the data migration).

The staging Postgres data is turned into a SQLite file offline by
``scripts/pg_to_sqlite`` (see docs/migration.md). Getting that file onto the
Railway volume is a two-step operator action in ``/ops → Import``:

1. **stage** — the browser streams the file to ``POST /api/ops/import-db``
   with its SHA-256 in ``X-Content-SHA256``. It lands next to the live
   database as ``<db>.import`` after the digest is checked and the file is
   opened read-only and verified (``integrity_check``, the migration ledger,
   row counts). Nothing live changes.
2. **apply** —``POST /api/ops/import-db/apply`` either restarts the process
   (``Settings.import_restart``; the production shape, because Litestream is
   replicating the live file and must observe the swap from a cold start — the
   entrypoint renames ``<db>.import`` into place before Litestream starts) or,
   for local/dev runs with no supervisor, swaps the file in place and reopens
   every connection.

Nothing here deletes the old database until a verified replacement exists,
and the entrypoint only performs the rename when the staged file is present.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.db.migrate import migration_files

log = logging.getLogger(__name__)

STAGED_SUFFIX = ".import"
INFO_SUFFIX = ".import.json"
COUNT_TABLES = (
    "pages", "taxonomy_nodes", "recipes", "recipe_ingredients", "recipe_steps",
    "ingredient_resolutions", "recipe_clusters", "recipe_exports", "jobs",
    "job_items", "human_reviews", "audit_log", "operators",
)
RESTART_EXIT_CODE = 3


class ImportError_(Exception):
    """A staged file was rejected (bad digest, not SQLite, schema mismatch)."""


@dataclass(frozen=True)
class Paths:
    live: Path

    @property
    def staged(self) -> Path:
        return Path(str(self.live) + STAGED_SUFFIX)

    @property
    def info(self) -> Path:
        return Path(str(self.live) + INFO_SUFFIX)

    @property
    def partial(self) -> Path:
        return Path(str(self.live) + STAGED_SUFFIX + ".part")


def inspect(path: Path) -> dict[str, Any]:
    """Open ``path`` read-only and describe it; raise ImportError_ if it is
    not a healthy Spiritolo database."""
    try:
        raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ImportError_(f"not a SQLite file: {exc}") from None
    try:
        try:
            ok = raw.execute("pragma integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ImportError_(f"not a SQLite database: {exc}") from None
        if ok != "ok":
            raise ImportError_(f"integrity_check failed: {ok}")
        tables = {r[0] for r in raw.execute("select name from sqlite_master where type = 'table'")}
        if "schema_migrations" not in tables:
            raise ImportError_("no schema_migrations table: not built by the Spiritolo migrations")
        applied = sorted(r[0] for r in raw.execute("select filename from schema_migrations"))
        bundled = [name for name, _ in migration_files()]
        unknown = sorted(set(applied) - set(bundled))
        if unknown:
            raise ImportError_(f"file was built by migrations this build does not know: {unknown}")
        counts = {t: raw.execute(f"select count(*) from {t}").fetchone()[0] for t in COUNT_TABLES if t in tables}
        return {
            "bytes": path.stat().st_size,
            "migrations": applied,
            "pending_migrations": sorted(set(bundled) - set(applied)),
            "counts": counts,
        }
    finally:
        raw.close()


def stage(paths: Paths, chunks: Iterable[bytes], expected_sha256: str) -> dict[str, Any]:
    """Write ``chunks`` to the staged path once the digest matches and the
    file verifies. Returns the stored info record."""
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ImportError_("X-Content-SHA256 must be a 64-char hex digest")
    paths.live.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with open(paths.partial, "wb") as f:
        for chunk in chunks:
            f.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    try:
        if size == 0:
            raise ImportError_("empty upload")
        actual = digest.hexdigest()
        if actual != expected:
            raise ImportError_(f"digest mismatch: body is {actual}, header says {expected}")
        info = inspect(paths.partial)
    except BaseException:
        paths.partial.unlink(missing_ok=True)
        raise
    info["operators_carried"] = carry_operators(paths.partial, paths.live)
    info.update({"sha256": actual, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    os.replace(paths.partial, paths.staged)
    paths.info.write_text(json.dumps(info))
    return info


def carry_operators(staged: Path, live: Path) -> int:
    """An ETL'd file has no operators (Supabase had none), so applying it
    would log everyone out and reopen first-time setup. If the staged file
    carries no operators, copy the live ``operators`` + ``passkeys`` into it.
    Returns the number of operators carried over."""
    if not live.is_file():
        return 0
    raw = sqlite3.connect(staged)
    try:
        if raw.execute("select count(*) from operators").fetchone()[0]:
            return 0
        raw.execute("attach database ? as live", (str(live),))
        try:
            with raw:
                raw.execute("insert into main.operators select * from live.operators")
                raw.execute("insert into main.passkeys select * from live.passkeys")
                n = raw.execute("select count(*) from main.operators").fetchone()[0]
        finally:
            raw.execute("detach database live")
        return n
    finally:
        raw.close()


def staged_info(paths: Paths) -> dict[str, Any] | None:
    if not paths.staged.is_file():
        return None
    try:
        return json.loads(paths.info.read_text())
    except (OSError, ValueError):
        return {"bytes": paths.staged.stat().st_size}


def discard(paths: Paths) -> bool:
    found = paths.staged.exists()
    paths.staged.unlink(missing_ok=True)
    paths.info.unlink(missing_ok=True)
    paths.partial.unlink(missing_ok=True)
    return found


def swap_files(paths: Paths) -> None:
    """Move the staged file into place. Callers must have closed every
    connection to the live file first. Mirrors the rename in entrypoint.sh."""
    if not paths.staged.is_file():
        raise ImportError_("nothing staged")
    for suffix in ("-wal", "-shm"):
        Path(str(paths.live) + suffix).unlink(missing_ok=True)
    os.replace(paths.staged, paths.live)
    paths.info.unlink(missing_ok=True)


def schedule_exit(delay: float = 0.75, code: int = RESTART_EXIT_CODE) -> None:
    """Exit the process shortly, so the HTTP response gets out first. The
    supervisor (Litestream -exec under Railway's restart policy) brings a
    fresh process up, whose entrypoint performs the swap."""
    def _bye() -> None:
        time.sleep(delay)
        log.warning("import-db: restarting the process to apply the staged database")
        os._exit(code)
    threading.Thread(target=_bye, name="import-restart", daemon=True).start()
