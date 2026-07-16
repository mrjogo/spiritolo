"""Tests for the SQLite pages -> Postgres pages importer.

Pure-mapping tests run with no DB; the integration tests need TEST_DB_URL (they
skip cleanly without it) and assert the actual UPSERT round-trip + idempotency.
"""
from __future__ import annotations

import pytest

from corpus_loader.import_pages import import_pages, map_row

_BASE = {
    "url": "https://x/a",
    "site": "x",
    "status": "ok",
    "content_type": "likely_drink_recipe",
    "discovered_at": "2026-01-01T00:00:00Z",
    "fetched_at": "2026-01-02T00:00:00Z",
    "html_path": "x/a.html",
    "disabled_reason": None,
}


def _row(**kw):
    return {**_BASE, **kw}


# --------------------------------------------------------------------------
# Pure mapping — no DB.
# --------------------------------------------------------------------------

def test_fetched_page_maps_to_ok_not_denylisted():
    m = map_row(_row(status="ok", html_path="x/a.html"))
    assert m["fetch_status"] == "ok"
    assert m["denylist"] is False
    assert m["content_type"] == "likely_drink_recipe"
    assert "corpus_key" not in m  # stays NULL; load_corpus sets it


def test_blocked_page_stays_blocked_and_denylisted_even_with_html():
    # A blocked page saves HTML (the block page) but must never be extracted.
    m = map_row(_row(status="blocked", html_path="x/blk.html", content_type=None))
    assert m["fetch_status"] == "blocked"
    assert m["denylist"] is True


def test_failed_page_maps_to_failed():
    m = map_row(_row(status="failed", html_path=None, content_type=None))
    assert m["fetch_status"] == "failed"
    assert m["denylist"] is False


def test_pending_page_has_null_fetch_status():
    m = map_row(_row(status="pending", html_path=None, fetched_at=None, content_type=None))
    assert m["fetch_status"] is None
    assert m["denylist"] is False


def test_disabled_reason_denylists_and_carries_over():
    m = map_row(_row(status="ok", disabled_reason="manual override"))
    assert m["denylist"] is True
    assert m["denylist_reason"] == "manual override"


# --------------------------------------------------------------------------
# Integration — TEST_DB_URL required (skips otherwise).
# --------------------------------------------------------------------------

def _seed(sqlite_pages, **kw):
    row = {**_row(**kw), "sitemap_source": None, "attempts": 0, "fetch_error": None}
    sqlite_pages.execute(
        "insert into pages (site, url, status, content_type, sitemap_source, "
        "attempts, discovered_at, fetched_at, fetch_error, html_path, disabled_reason) "
        "values (:site, :url, :status, :content_type, :sitemap_source, :attempts, "
        ":discovered_at, :fetched_at, :fetch_error, :html_path, :disabled_reason)",
        row,
    )


def test_import_copies_rows_with_corpus_key_null(sqlite_pages, pg_conn):
    _seed(sqlite_pages, url="https://x/1", content_type="likely_drink_recipe")
    _seed(sqlite_pages, url="https://x/2", status="failed", html_path=None, content_type=None)
    stats = import_pages(sqlite_pages, pg_conn)

    assert stats == {"read": 2, "extractable": 1, "denylisted": 0}
    rows = {
        r[0]: r
        for r in pg_conn.execute(
            "select url, content_type, fetch_status, corpus_key, denylist, discovered_at "
            "from pages"
        ).fetchall()
    }
    assert rows["https://x/1"][1] == "likely_drink_recipe"
    assert rows["https://x/1"][2] == "ok"
    assert rows["https://x/1"][3] is None  # corpus_key NULL until HTML is in the object store
    assert rows["https://x/1"][5] is not None  # discovered_at coerced to timestamptz
    assert rows["https://x/2"][2] == "failed"


def test_import_is_idempotent(sqlite_pages, pg_conn):
    _seed(sqlite_pages, url="https://x/1")
    import_pages(sqlite_pages, pg_conn)
    import_pages(sqlite_pages, pg_conn)
    assert pg_conn.execute("select count(*) from pages").fetchone()[0] == 1


def test_reimport_updates_changed_fields(sqlite_pages, pg_conn):
    _seed(sqlite_pages, url="https://x/1", content_type="other")
    import_pages(sqlite_pages, pg_conn)
    sqlite_pages.execute("update pages set content_type='confirmed_drink' where url='https://x/1'")
    import_pages(sqlite_pages, pg_conn)
    ct = pg_conn.execute(
        "select content_type from pages where url='https://x/1'"
    ).fetchone()[0]
    assert ct == "confirmed_drink"


def test_reimport_never_clobbers_corpus_key(sqlite_pages, pg_conn):
    # If load_corpus already set corpus_key, a re-import must not reset it to NULL.
    _seed(sqlite_pages, url="https://x/1")
    import_pages(sqlite_pages, pg_conn)
    pg_conn.execute("update pages set corpus_key='deadbeef' where url='https://x/1'")
    import_pages(sqlite_pages, pg_conn)
    r2 = pg_conn.execute("select corpus_key from pages where url='https://x/1'").fetchone()[0]
    assert r2 == "deadbeef"


def test_import_batches_across_chunks(sqlite_pages, pg_conn):
    # chunk_size below the row count exercises the multi-chunk executemany path.
    for i in range(5):
        _seed(sqlite_pages, url=f"https://x/{i}", content_type="likely_drink_recipe")
    stats = import_pages(sqlite_pages, pg_conn, chunk_size=2)
    assert stats == {"read": 5, "extractable": 5, "denylisted": 0}
    assert pg_conn.execute("select count(*) from pages").fetchone()[0] == 5
