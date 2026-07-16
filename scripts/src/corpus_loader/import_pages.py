"""Import the scraper's SQLite ``pages`` work-queue into the hosted Postgres
``pages`` table.

This is the one-time move of per-URL crawl state — the URLs, their LLM
``content_type`` classifications, and each page's fetch outcome — from the local
``data/scraper.db`` into the cloud, so the Zone-2 ``extract`` stage has a queue
to work from without re-crawling or re-classifying.

The HTML bytes are NOT touched here; those go to the object store via
``load_corpus``, which also sets ``pages.corpus_key``. This importer leaves
``corpus_key`` NULL by design: a page becomes extractable (``corpus_key`` non-null)
only once its HTML is confirmed in the object store.

Idempotent: re-running UPSERTs by ``url``, so a re-import after a fix is safe.
"""
from __future__ import annotations

import sqlite3
from typing import Any

# SQLite `pages` columns this reads (scraper/src/scraper/db.py).
_SQLITE_COLUMNS = (
    "url", "site", "status", "content_type",
    "discovered_at", "fetched_at", "html_path", "disabled_reason",
)

# The Zone-1 classifier verdicts that make a page extract-eligible — in lockstep
# with extract.RECIPE_CONTENT_TYPES / scraper.db.EXTRACT_CONTENT_TYPES.
_RECIPE_LABELS = ("likely_drink_recipe", "confirmed_drink")


def map_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map one SQLite ``pages`` row to the Postgres ``pages`` column set.

    - ``denylist`` is set for a blocked page or any page carrying a
      ``disabled_reason``; that reason carries over verbatim.
    - ``fetch_status`` collapses the SQLite ``status`` onto the Postgres CHECK
      domain (``ok`` / ``blocked`` / ``failed``), or NULL for a still-``pending``
      page. A blocked page stays ``blocked`` even though it has saved HTML — that
      HTML is the block page, not content, so it must never be extracted.
    - ``corpus_key`` is omitted (stays NULL); ``load_corpus`` sets it once the page's
      HTML is in the object store.
    """
    status = row.get("status")
    disabled_reason = row.get("disabled_reason")
    html_path = row.get("html_path")

    if status == "blocked":
        fetch_status = "blocked"
    elif status == "failed":
        fetch_status = "failed"
    elif html_path:
        fetch_status = "ok"
    else:
        fetch_status = None

    return {
        "url": row["url"],
        "site": row["site"],
        "content_type": row.get("content_type"),
        "denylist": status == "blocked" or bool(disabled_reason),
        "denylist_reason": disabled_reason,
        "fetch_status": fetch_status,
        "discovered_at": row.get("discovered_at"),
        "fetched_at": row.get("fetched_at"),
    }


_UPSERT = """
insert into pages
  (url, site, content_type, denylist, denylist_reason, fetch_status,
   discovered_at, fetched_at)
values
  (%(url)s, %(site)s, %(content_type)s, %(denylist)s, %(denylist_reason)s,
   %(fetch_status)s, %(discovered_at)s, %(fetched_at)s)
on conflict (url) do update set
  site            = excluded.site,
  content_type    = excluded.content_type,
  denylist        = excluded.denylist,
  denylist_reason = excluded.denylist_reason,
  fetch_status    = excluded.fetch_status,
  discovered_at   = excluded.discovered_at,
  fetched_at      = excluded.fetched_at
"""


def _iter_sqlite_pages(sqlite_conn: sqlite3.Connection):
    sqlite_conn.row_factory = sqlite3.Row
    cols = ", ".join(_SQLITE_COLUMNS)
    for row in sqlite_conn.execute(f"select {cols} from pages"):
        yield dict(row)


# Rows per UPSERT batch. A chunked ``executemany`` inside one transaction per
# chunk replaces a per-row execute+commit — on a half-million-row import over a
# remote pooler that is the difference between minutes and hours.
_CHUNK_SIZE = 5000


def import_pages(
    sqlite_conn: sqlite3.Connection, pg_conn, *, chunk_size: int = _CHUNK_SIZE
) -> dict[str, int]:
    """UPSERT every SQLite ``pages`` row into Postgres ``pages`` (keyed ``url``).

    Rows are UPSERTed in chunks of ``chunk_size`` via ``executemany`` (one
    transaction per chunk) rather than one autocommit statement per row — same
    result, but round-trips and commits amortize across the chunk.

    Returns a summary: total ``read``, how many carry a recipe verdict
    (``extractable`` — what ``extract`` picks up once the HTML is in the
    object store), and how many are ``denylisted`` — a quick sanity check for
    the operator.
    """
    read = extractable = denylisted = 0
    batch: list[dict[str, Any]] = []
    for sqlite_row in _iter_sqlite_pages(sqlite_conn):
        mapped = map_row(sqlite_row)
        read += 1
        if mapped["content_type"] in _RECIPE_LABELS:
            extractable += 1
        if mapped["denylist"]:
            denylisted += 1
        batch.append(mapped)
        if len(batch) >= chunk_size:
            _upsert_batch(pg_conn, batch)
            batch = []
    if batch:
        _upsert_batch(pg_conn, batch)
    return {"read": read, "extractable": extractable, "denylisted": denylisted}


def _upsert_batch(pg_conn, batch: list[dict[str, Any]]) -> None:
    """UPSERT one chunk in a single transaction. ``pg_conn.transaction()`` opens
    an explicit block even on an autocommit connection, so the whole chunk
    commits once instead of once per row."""
    with pg_conn.transaction(), pg_conn.cursor() as cur:
        cur.executemany(_UPSERT, batch)
