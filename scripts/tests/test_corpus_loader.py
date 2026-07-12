"""Corpus loader (WS-B20): gzip + write-once upload of cached HTML to R2, and
the pages.r2_key backfill. Every test here stubs the S3-compat client — no
network, no live R2 (see docs/redesign.md WS-B20 + CLAUDE.md hard rules).
"""
from __future__ import annotations

import gzip

import pytest

from corpus_loader.keys import sha256_key
from corpus_loader.load import load
from corpus_loader.backfill_pages import backfill_pages


class FakeS3Client:
    """Minimal S3-compat double: an in-memory object store.

    ``head_object`` mirrors the real client's contract (used by
    ``corpus_loader.load.key_exists``): returns a response dict when the key
    exists, ``None`` when it doesn't — no exception-type coupling needed in
    tests. Records every ``put_object``/``delete_object`` call so tests can
    assert on exactly what the loader sent (and that it never deletes).
    """

    def __init__(self, preexisting: dict[str, bytes] | None = None):
        self.objects: dict[str, bytes] = dict(preexisting or {})
        self.put_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def head_object(self, *, Bucket: str, Key: str):
        if Key in self.objects:
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}
        return None

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)


def test_object_body_is_gzip():
    client = FakeS3Client()
    html = b"<html><body>Negroni</body></html>"
    load(client, "spiritolo-corpus", "https://example.com/negroni", html)

    assert len(client.put_calls) == 1
    body = client.put_calls[0]["Body"]
    assert gzip.decompress(body) == html


def test_object_metadata():
    client = FakeS3Client()
    url = "https://example.com/negroni"
    html = b"<html></html>"
    load(client, "spiritolo-corpus", url, html)

    kwargs = client.put_calls[0]
    assert kwargs["Key"] == sha256_key(url)
    assert kwargs["ContentType"] == "text/html"
    assert kwargs["ContentEncoding"] == "gzip"
    assert kwargs["Metadata"] == {"url": url}


def test_skip_existing_key():
    url = "https://example.com/negroni"
    key = sha256_key(url)
    client = FakeS3Client(preexisting={key: b"already-there"})

    wrote = load(client, "spiritolo-corpus", url, b"<html>new</html>")

    assert wrote is False
    assert client.put_calls == []  # write-once: no re-put on an existing key


def test_no_delete_or_overwrite_calls():
    url = "https://example.com/negroni"
    client = FakeS3Client()

    load(client, "spiritolo-corpus", url, b"<html>first</html>")
    # A second load() of the SAME url must skip, not overwrite.
    load(client, "spiritolo-corpus", url, b"<html>different-body</html>")

    assert len(client.put_calls) == 1  # only the first call actually wrote
    assert client.delete_calls == []


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakePagesDB:
    """Stand-in for a psycopg-style connection (``conn.execute(sql, params)``
    returning a cursor), holding an in-memory `pages` row set so
    ``backfill_pages`` can be unit-tested with no TEST_DB_URL / network."""

    def __init__(self, rows):
        # rows: list of dicts with at least id/url/r2_key/site keys.
        self.rows = {row["id"]: dict(row) for row in rows}

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select id, url from pages where r2_key is null"):
            matched = [
                (row["id"], row["url"])
                for row in self.rows.values()
                if row["r2_key"] is None
            ]
            return _FakeCursor(matched)
        if normalized.startswith("update pages set r2_key"):
            r2_key, row_id = params
            self.rows[row_id]["r2_key"] = r2_key
            return _FakeCursor([])
        raise AssertionError(f"unexpected SQL in FakePagesDB: {sql!r}")


def test_backfill_pages_sets_r2_key():
    rows = [
        {"id": 1, "url": "https://a.example/x", "r2_key": None, "site": "a"},
        {"id": 2, "url": "https://b.example/y", "r2_key": None, "site": "b"},
        {"id": 3, "url": "https://c.example/z", "r2_key": "already-set", "site": "c"},
    ]
    db = FakePagesDB(rows)

    updated = backfill_pages(db)

    assert updated == 2
    assert db.rows[1]["r2_key"] == sha256_key("https://a.example/x")
    assert db.rows[2]["r2_key"] == sha256_key("https://b.example/y")
    # Every row not lacking r2_key, and every other column, is left untouched.
    assert db.rows[3]["r2_key"] == "already-set"
    assert db.rows[1]["site"] == "a"
    assert db.rows[2]["site"] == "b"
    assert db.rows[3]["site"] == "c"
