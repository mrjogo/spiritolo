"""Read-only object-store corpus reader.

The HTML corpus is one of two durable inputs (the other being the ``pages``
row — see supabase/migrations/20260715090000_pages.sql, and the write-once
loader in scripts/src/corpus_loader). It is write-once and read-only after the
one-time load: this module is strictly a reader — it exposes exactly one
operation, ``CorpusReader.read_html``, and no put/write/delete surface.

Keys are ``sha256(url)``, matching scripts/src/corpus_loader/keys.py exactly
(the same one-liner, deliberately duplicated rather than shared across the two
packages — not worth a shared helper package for a single line).
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
    """The object-store key for ``url``: sha256(url.encode()).hexdigest().

    Deliberately not canonicalized — the caller owns any url normalization.
    """
    return hashlib.sha256(url.encode()).hexdigest()


class CorpusReader:
    """Read-only client for the object-store HTML corpus.

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


def _s3_config():
    """boto3 client config for an S3-compatible store that isn't AWS S3.

    Virtual-host addressing (``<bucket>.<endpoint>``): boto3 defaults to
    path-style for a custom ``endpoint_url``, which Tigris/Railway reject with a
    request timeout. ``AWS_S3_URL_STYLE=path`` forces path-style if ever needed.
    Retries + timeouts keep a transient miss from failing an extract read.
    (Duplicated from scripts/src/corpus_loader/load.py — one small helper isn't
    worth a shared package across the two zones; see key_for's note.)
    """
    from botocore.config import Config

    style = "path" if os.environ.get("AWS_S3_URL_STYLE", "").startswith("path") else "virtual"
    return Config(
        s3={"addressing_style": style},
        retries={"max_attempts": 8, "mode": "standard"},
        connect_timeout=15,
        read_timeout=60,
    )


def default_reader() -> CorpusReader:
    """Build the real corpus reader from the standard ``AWS_*`` env vars
    (``AWS_ENDPOINT_URL`` / ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` /
    ``AWS_S3_BUCKET_NAME``, optional ``AWS_DEFAULT_REGION``) — the names Railway's
    bucket "AWS SDK" preset injects and boto3 reads by convention. Any
    S3-compatible object store works.

    Not exercised by any test — those inject a fake client instead (see
    ingredients/tests/test_corpus_reader.py). Used by the worker at runtime.
    """
    import boto3

    raw = boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"),
        config=_s3_config(),
    )
    return CorpusReader(_NotFoundIsNoneAdapter(raw), bucket=os.environ["AWS_S3_BUCKET_NAME"])


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
