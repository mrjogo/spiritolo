"""Read-only R2 corpus reader (WS-B6).

The HTML corpus is one of the two clean-slate inputs the v2.1 rebuild
preserves (the other being the ``pages`` row — see supabase/migrations/
20260715090000_pages.sql, and the write-once loader in
scripts/src/corpus_loader). It is write-once and read-only after the one-time
load: this module is strictly a reader — it exposes exactly one operation,
``CorpusReader.read_html``, and no put/write/delete surface.

Keys are ``sha256(url)``, matching scripts/src/corpus_loader/keys.py exactly
(same one-liner, deliberately not shared across the two packages — see
docs/redesign.md §8.6 YAGNI: no shared test-utils/helper package up front).
"""
from __future__ import annotations

import gzip
import hashlib
import os
from typing import Protocol


class CorpusMiss(Exception):
    """Raised by ``CorpusReader.read_html`` when no object exists for the key."""

    def __init__(self, key: str):
        super().__init__(f"no corpus object for key {key!r}")
        self.key = key


class GetObjectClient(Protocol):
    """The subset of the boto3 S3 client surface the reader needs.

    ``get_object`` returns a response dict (with a ``.read()``-able ``Body``)
    when the key exists and ``None`` when it doesn't — mirroring
    corpus_loader.load.S3Client's head_object contract so fakes need no
    exception-type coupling to boto3/botocore.
    """

    def get_object(self, *, Bucket: str, Key: str) -> dict | None: ...


def key_for(url: str) -> str:
    """The R2 object key for ``url``: sha256(url.encode()).hexdigest().

    Deliberately not canonicalized — the caller owns any url normalization.
    """
    return hashlib.sha256(url.encode()).hexdigest()


class CorpusReader:
    """Read-only client for the R2 HTML corpus.

    Exposes ``read_html`` only — no put/write/delete method, matching the
    write-once contract (see ``test_reader_is_read_only``).
    """

    def __init__(self, client: GetObjectClient, bucket: str):
        self._client = client
        self._bucket = bucket

    def read_html(self, key: str) -> str:
        """GET the gzipped object at ``key`` and return the decompressed
        HTML as a str. Raises ``CorpusMiss`` if no such object exists."""
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        if response is None:
            raise CorpusMiss(key)
        body = response["Body"]
        raw = body.read() if hasattr(body, "read") else bytes(body)
        return gzip.decompress(raw).decode("utf-8")


def default_reader() -> CorpusReader:
    """Build the real R2 corpus reader from ``R2_*`` env vars.

    Not exercised by any test — those inject a fake client instead (see
    ingredients/tests/test_corpus_reader.py). Used by the worker at runtime.
    """
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    raw = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    return CorpusReader(_NotFoundIsNoneAdapter(raw), bucket=os.environ["R2_BUCKET"])


class _NotFoundIsNoneAdapter:
    """Wraps a raw boto3 S3 client so ``get_object`` returns ``None`` on a
    missing key (matching ``GetObjectClient``) instead of raising botocore's
    ``ClientError``."""

    def __init__(self, boto_client):
        self._client = boto_client

    def get_object(self, *, Bucket: str, Key: str) -> dict | None:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(Bucket=Bucket, Key=Key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
