"""Read-only R2 corpus reader (WS-B6). No network: every test stubs the
S3-compat client (see docs/redesign.md B6 + CLAUDE.md hard rules).

The migration for `pages` (WS-B20, ingredients/tests/test_pages_migration.py)
is the ONE pages migration; this file covers only the reader module, per the
docs/redesign.md §4 reconciliation note.
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
