"""Upload each fetched page's local HTML into the corpus bucket and mark it
extractable.

The corpus is write-once — ``load`` skips any key already present. A page
becomes extractable only here: after its HTML is confirmed in the object
store do we set ``pages.r2_key``. Denylisted pages (blocked / disabled) and
pages with no saved HTML are skipped and never get an ``r2_key``, so
``extract`` never reads a block page or a missing object.

Run ``import_pages`` first — the ``r2_key`` update targets rows by ``url``, so
the Postgres ``pages`` rows must already exist.
"""
from __future__ import annotations

import pathlib
import sqlite3

from .keys import sha256_key
from .load import S3Client, load

# Fetched, non-denylisted pages: exactly the ones whose saved HTML is real
# content the extract stage should read.
_FETCHED_NOT_DENYLISTED = """
select url, html_path from pages
where html_path is not null and status <> 'blocked' and disabled_reason is null
"""


def load_corpus(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    s3_client: S3Client,
    bucket: str,
    html_root: str | pathlib.Path,
) -> dict[str, int]:
    """Upload every fetched page's HTML to the object store and set
    ``pages.r2_key``.

    ``html_root`` is the base directory the SQLite ``html_path`` values are
    relative to (``data/html``). Idempotent: ``load`` skips keys already in
    the object store, and the ``r2_key`` update is deterministic. A page whose
    local file is missing is counted and skipped, not fatal.
    """
    root = pathlib.Path(html_root)
    sqlite_conn.row_factory = sqlite3.Row
    uploaded = skipped_existing = missing = r2_key_set = not_in_pg = 0
    for row in sqlite_conn.execute(_FETCHED_NOT_DENYLISTED):
        url, html_path = row["url"], row["html_path"]
        path = root / html_path
        if not path.exists():
            missing += 1
            continue
        if load(s3_client, bucket, url, path.read_bytes()):
            uploaded += 1
        else:
            skipped_existing += 1
        # r2_key is set only if the page's Postgres row exists (import ran first).
        # A 0-row update means the HTML is in the object store but the page
        # isn't imported yet, so it's reported (not_in_pg) rather than counted
        # as a silent success.
        cur = pg_conn.execute(
            "update pages set r2_key = %s where url = %s", (sha256_key(url), url)
        )
        if cur.rowcount:
            r2_key_set += 1
        else:
            not_in_pg += 1
    return {
        "uploaded": uploaded,
        "skipped_existing": skipped_existing,
        "missing": missing,
        "r2_key_set": r2_key_set,
        "not_in_pg": not_in_pg,
    }
