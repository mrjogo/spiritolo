"""Read-only object-store corpus reader. No network: every test stubs the
S3-compat client (see CLAUDE.md hard rules).

The `pages` migration is covered by ingredients/tests/test_pages_migration.py;
this file covers only the reader module and adds no migration of its own.
"""
from __future__ import annotations

import gzip
import hashlib

import pytest

from ingredients.pipeline import corpus


class FakeGetObjectClient:
    """In-memory get_object double. Returns ``None`` on a missing key
    (mirrors corpus_loader.load's S3Client contract) rather than raising —
    no exception-type coupling to boto3/botocore needed in tests."""

    def __init__(self, objects: dict[str, bytes]):
        self._objects = objects

    def get_object(self, *, Bucket: str, Key: str):
        if Key not in self._objects:
            return None
        return {"Body": _FakeBody(self._objects[Key])}


class _FakeBody:
    """Mimics botocore's StreamingBody: a .read()-able wrapper over bytes."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_key_is_sha256_of_url():
    url = "https://example.com/negroni"
    key = corpus.key_for(url)
    assert key == hashlib.sha256(url.encode()).hexdigest()
    assert corpus.key_for(url) == corpus.key_for(url)  # stable across calls


def test_read_html_gunzips():
    html = "<html><body>Negroni</body></html>"
    key = corpus.key_for("https://example.com/negroni")
    client = FakeGetObjectClient({key: gzip.compress(html.encode("utf-8"))})
    reader = corpus.CorpusReader(client, bucket="spiritolo-corpus")

    assert reader.read_html(key) == html


def test_read_html_missing_key_raises_corpus_miss():
    client = FakeGetObjectClient({})
    reader = corpus.CorpusReader(client, bucket="spiritolo-corpus")

    with pytest.raises(corpus.CorpusMiss):
        reader.read_html("does-not-exist")


def test_reader_is_read_only():
    # The module (and the reader class) exposes no put/write/delete surface —
    # the corpus is write-once; the pipeline never mutates it after the
    # one-time load.
    for name in ("put_object", "write_html", "delete_html", "put_html"):
        assert not hasattr(corpus, name)
        assert not hasattr(corpus.CorpusReader, name)


def _scraper_cache(tmp_path, pages: dict[str, str | None]):
    """A scraper.db + data/html pair as the scraper leaves them: plain HTML
    under html_root, located by pages.html_path (None = not fetched)."""
    import sqlite3

    root = tmp_path / "html"
    db = tmp_path / "scraper.db"
    conn = sqlite3.connect(db)
    conn.execute("create table pages (url text, html_path text)")
    for i, (url, html) in enumerate(pages.items()):
        path = None
        if html is not None:
            path = f"site/{i}.html"
            (root / "site").mkdir(parents=True, exist_ok=True)
            (root / path).write_text(html)
        conn.execute("insert into pages values (?, ?)", (url, path))
    conn.commit()
    conn.close()
    return root, db


def test_local_reader_reads_by_sha256_of_url(tmp_path):
    root, db = _scraper_cache(tmp_path, {"https://example.com/negroni": "<p>Negroni</p>"})
    reader = corpus.LocalCorpusReader(root, db)

    assert reader.read_html(corpus.key_for("https://example.com/negroni")) == "<p>Negroni</p>"


def test_local_reader_unfetched_or_deleted_page_is_a_miss(tmp_path):
    root, db = _scraper_cache(tmp_path, {"https://a.example/": None, "https://b.example/": "x"})
    (root / "site" / "1.html").unlink()
    reader = corpus.LocalCorpusReader(root, db)

    for url in ("https://a.example/", "https://b.example/", "https://c.example/"):
        with pytest.raises(corpus.CorpusMiss):
            reader.read_html(corpus.key_for(url))


def test_default_reader_uses_corpus_dir_and_sibling_index(tmp_path, monkeypatch):
    root, _ = _scraper_cache(tmp_path, {"https://example.com/": "<p>hi</p>"})
    monkeypatch.setenv("CORPUS_DIR", str(root))
    monkeypatch.delenv("CORPUS_INDEX", raising=False)

    reader = corpus.default_reader()

    assert isinstance(reader, corpus.LocalCorpusReader)
    assert reader.read_html(corpus.key_for("https://example.com/")) == "<p>hi</p>"
