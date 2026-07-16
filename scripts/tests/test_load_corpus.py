"""Tests for the local-HTML -> object-store corpus upload that also marks pages
extractable (sets ``pages.corpus_key``). Needs TEST_DB_URL (skips otherwise); the
S3 client is a fake.
"""
from __future__ import annotations

from corpus_loader.import_pages import import_pages
from corpus_loader.keys import sha256_key
from corpus_loader.upload import load_corpus


class FakeS3:
    """In-memory stand-in matching the S3Client protocol load() uses."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_object(self, *, Bucket, Key):
        return {"Key": Key} if (Bucket, Key) in self.objects else None

    def put_object(self, *, Bucket, Key, Body, **_kw):
        self.objects[(Bucket, Key)] = Body
        return {}


def _seed(sqlite_pages, tmp_path, *, url, rel, html="<html>x</html>",
          status="ok", disabled_reason=None, write_file=True):
    sqlite_pages.execute(
        "insert into pages (site, url, status, content_type, discovered_at, "
        "fetched_at, html_path, disabled_reason) "
        "values ('x', :url, :status, 'likely_drink_recipe', '2026-01-01T00:00:00Z', "
        "'2026-01-02T00:00:00Z', :rel, :disabled)",
        {"url": url, "status": status, "rel": rel, "disabled": disabled_reason},
    )
    if write_file:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html)


def test_uploads_fetched_html_and_sets_corpus_key(sqlite_pages, pg_conn, tmp_path):
    _seed(sqlite_pages, tmp_path, url="https://x/1", rel="x/1.html")
    import_pages(sqlite_pages, pg_conn)  # rows must exist for the corpus_key update

    s3 = FakeS3()
    stats = load_corpus(sqlite_pages, pg_conn, s3, "corpus", tmp_path)

    assert stats["uploaded"] == 1
    assert ("corpus", sha256_key("https://x/1")) in s3.objects
    r2 = pg_conn.execute(
        "select corpus_key from pages where url = 'https://x/1'"
    ).fetchone()[0]
    assert r2 == sha256_key("https://x/1")


def test_denylisted_pages_are_skipped(sqlite_pages, pg_conn, tmp_path):
    _seed(sqlite_pages, tmp_path, url="https://x/blk", rel="x/blk.html", status="blocked")
    _seed(sqlite_pages, tmp_path, url="https://x/dis", rel="x/dis.html",
          disabled_reason="manual")
    import_pages(sqlite_pages, pg_conn)

    s3 = FakeS3()
    stats = load_corpus(sqlite_pages, pg_conn, s3, "corpus", tmp_path)

    assert stats["uploaded"] == 0
    assert s3.objects == {}
    r2s = [
        r[0] for r in pg_conn.execute("select corpus_key from pages").fetchall()
    ]
    assert r2s == [None, None]  # neither becomes extractable


def test_missing_local_file_is_counted_not_fatal(sqlite_pages, pg_conn, tmp_path):
    _seed(sqlite_pages, tmp_path, url="https://x/gone", rel="x/gone.html", write_file=False)
    import_pages(sqlite_pages, pg_conn)

    stats = load_corpus(sqlite_pages, pg_conn, FakeS3(), "corpus", tmp_path)

    assert stats == {
        "uploaded": 0, "skipped_existing": 0, "missing": 1,
        "corpus_key_set": 0, "not_in_pg": 0,
    }
    r2 = pg_conn.execute(
        "select corpus_key from pages where url = 'https://x/gone'"
    ).fetchone()[0]
    assert r2 is None


def test_load_before_import_is_reported_not_silently_lost(sqlite_pages, pg_conn, tmp_path):
    # Running load-corpus before import-pages: the HTML uploads, but there's no
    # Postgres row to mark, so it's flagged not_in_pg rather than counted as a
    # silent corpus_key_set — the operator learns to run import-pages first.
    _seed(sqlite_pages, tmp_path, url="https://x/1", rel="x/1.html")  # no import_pages()

    s3 = FakeS3()
    stats = load_corpus(sqlite_pages, pg_conn, s3, "corpus", tmp_path)

    assert stats["uploaded"] == 1
    assert stats["not_in_pg"] == 1
    assert stats["corpus_key_set"] == 0
    assert pg_conn.execute("select count(*) from pages").fetchone()[0] == 0


def test_write_once_existing_key_still_sets_corpus_key(sqlite_pages, pg_conn, tmp_path):
    _seed(sqlite_pages, tmp_path, url="https://x/1", rel="x/1.html")
    import_pages(sqlite_pages, pg_conn)

    s3 = FakeS3()
    s3.objects[("corpus", sha256_key("https://x/1"))] = b"already-there"
    stats = load_corpus(sqlite_pages, pg_conn, s3, "corpus", tmp_path)

    assert stats["skipped_existing"] == 1
    assert stats["uploaded"] == 0
    assert s3.objects[("corpus", sha256_key("https://x/1"))] == b"already-there"  # not overwritten
    r2 = pg_conn.execute(
        "select corpus_key from pages where url = 'https://x/1'"
    ).fetchone()[0]
    assert r2 == sha256_key("https://x/1")  # still marked extractable


def test_load_batches_and_threads_across_chunks(sqlite_pages, pg_conn, tmp_path):
    # More rows than chunk_size, >1 worker: exercises the threaded upload + the
    # batched corpus_key flush, and asserts every key still lands exactly once.
    for i in range(5):
        _seed(sqlite_pages, tmp_path, url=f"https://x/{i}", rel=f"x/{i}.html")
    import_pages(sqlite_pages, pg_conn)

    s3 = FakeS3()
    stats = load_corpus(sqlite_pages, pg_conn, s3, "corpus", tmp_path, workers=3, chunk_size=2)

    assert stats["uploaded"] == 5
    assert stats["corpus_key_set"] == 5
    assert len(s3.objects) == 5
    keys = {r[0] for r in pg_conn.execute("select corpus_key from pages").fetchall()}
    assert keys == {sha256_key(f"https://x/{i}") for i in range(5)}
