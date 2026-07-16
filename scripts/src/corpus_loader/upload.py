"""Upload each fetched page's local HTML into the corpus bucket and mark it
extractable.

The corpus is write-once — ``load`` skips any key already present. A page
becomes extractable only here: after its HTML is confirmed in the object
store do we set ``pages.corpus_key``. Denylisted pages (blocked / disabled) and
pages with no saved HTML are skipped and never get an ``corpus_key``, so
``extract`` never reads a block page or a missing object.

Run ``import_pages`` first — the ``corpus_key`` update targets rows by ``url``, so
the Postgres ``pages`` rows must already exist.
"""
from __future__ import annotations

import pathlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from .keys import sha256_key
from .load import S3Client, load

# Fetched, non-denylisted pages: exactly the ones whose saved HTML is real
# content the extract stage should read.
_FETCHED_NOT_DENYLISTED = """
select url, html_path from pages
where html_path is not null and status <> 'blocked' and disabled_reason is null
"""

# Concurrent uploads (network-bound S3 round-trips) and rows per corpus_key-update
# batch. Threads do only the S3 work; the DB writes stay on the main thread.
_WORKERS = 24
_CHUNK_SIZE = 1000


def load_corpus(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    s3_client: S3Client,
    bucket: str,
    html_root: str | pathlib.Path,
    *,
    workers: int = _WORKERS,
    chunk_size: int = _CHUNK_SIZE,
) -> dict[str, int]:
    """Upload every fetched page's HTML to the object store and set
    ``pages.corpus_key``.

    Uploads run across a ``workers``-wide thread pool (the work is network-bound
    S3 round-trips); the deterministic ``corpus_key`` writes are batched ``chunk_size``
    at a time as uploads land. Only the main thread touches ``pg_conn`` (a psycopg
    connection is not shared across threads), so the DB stays single-writer.

    ``html_root`` is the base directory the SQLite ``html_path`` values are
    relative to (``data/html``). Idempotent: ``load`` skips keys already in
    the object store, and the ``corpus_key`` update is deterministic. A page whose
    local file is missing is counted and skipped, not fatal.
    """
    root = pathlib.Path(html_root)
    sqlite_conn.row_factory = sqlite3.Row
    rows = [
        (row["url"], row["html_path"])
        for row in sqlite_conn.execute(_FETCHED_NOT_DENYLISTED)
    ]

    uploaded = skipped_existing = missing = corpus_key_set = not_in_pg = 0
    pending: list[str] = []

    def _upload(item: tuple[str, str]) -> tuple[str, str]:
        url, html_path = item
        path = root / html_path
        if not path.exists():
            return url, "missing"
        return url, "uploaded" if load(s3_client, bucket, url, path.read_bytes()) else "skipped"

    def _flush() -> None:
        # Set corpus_key for the batch in one statement. rowcount is the rows that
        # existed (import ran first); the rest are reported not_in_pg rather than
        # counted as a silent success.
        nonlocal corpus_key_set, not_in_pg
        if not pending:
            return
        keys = [sha256_key(u) for u in pending]
        with pg_conn.transaction(), pg_conn.cursor() as cur:
            cur.execute(
                "update pages p set corpus_key = d.k "
                "from unnest(%s::text[], %s::text[]) as d(url, k) "
                "where p.url = d.url",
                (pending, keys),
            )
            updated = cur.rowcount
        corpus_key_set += updated
        not_in_pg += len(pending) - updated
        pending.clear()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, status in pool.map(_upload, rows):
            if status == "missing":
                missing += 1
                continue
            if status == "uploaded":
                uploaded += 1
            else:
                skipped_existing += 1
            pending.append(url)
            if len(pending) >= chunk_size:
                _flush()
    _flush()

    return {
        "uploaded": uploaded,
        "skipped_existing": skipped_existing,
        "missing": missing,
        "corpus_key_set": corpus_key_set,
        "not_in_pg": not_in_pg,
    }
