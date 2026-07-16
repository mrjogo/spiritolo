"""Write-once upload of one cached HTML page to the object-store corpus.

``load()`` is the pure, injectable core: it takes an S3-compat client (real or
fake), gzips the HTML, and ``put_object``s it keyed ``sha256(url)`` — unless
that key already exists, in which case it skips (write-once, idempotent
re-run). It never calls ``delete_object`` and never overwrites an existing
key — the corpus is write-once by construction.

Tests inject a fake client (see scripts/tests/test_corpus_loader.py); the real
client used operationally is built by ``default_client()`` below, from the
``S3_*`` env vars, and is exercised by no test (no network in CI/dev).
"""
from __future__ import annotations

import gzip
import os
from typing import Protocol

from .keys import sha256_key


class S3Client(Protocol):
    """The subset of the boto3 S3 client surface the loader needs.

    ``head_object`` returns a response dict when the key exists and ``None``
    when it doesn't — real boto3 instead raises ``botocore.exceptions.
    ClientError`` on a 404; ``default_client()`` below adapts that so callers
    (and the fake client tests inject) share one plain contract.
    """

    def head_object(self, *, Bucket: str, Key: str) -> dict | None: ...
    def put_object(self, **kwargs: object) -> dict: ...


def key_exists(client: S3Client, bucket: str, key: str) -> bool:
    return client.head_object(Bucket=bucket, Key=key) is not None


def load(client: S3Client, bucket: str, url: str, html: bytes) -> bool:
    """Gzip ``html`` and upload it to ``bucket`` keyed ``sha256(url)``.

    Returns ``True`` if an object was written, ``False`` if the key already
    existed and the upload was skipped. Never deletes or overwrites.
    """
    key = sha256_key(url)
    if key_exists(client, bucket, key):
        return False
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=gzip.compress(html, compresslevel=9),
        ContentType="text/html",
        ContentEncoding="gzip",
        Metadata={"url": url},
    )
    return True


def _s3_config():
    """boto3 client config for an S3-compatible store that isn't AWS S3.

    - ``addressing_style`` virtual-host (``<bucket>.<endpoint>``): boto3 defaults
      to path-style for a custom ``endpoint_url``, which Tigris/Railway reject
      with a request timeout. ``AWS_S3_URL_STYLE=path`` forces path-style if a
      future store ever needs it.
    - retries + timeouts so a transient or hung request retries instead of
      aborting a long bulk upload.
    """
    from botocore.config import Config

    style = "path" if os.environ.get("AWS_S3_URL_STYLE", "").startswith("path") else "virtual"
    return Config(
        s3={"addressing_style": style},
        retries={"max_attempts": 8, "mode": "standard"},
        connect_timeout=15,
        read_timeout=60,
    )


def default_client():
    """Build the real S3 client from the standard ``AWS_*`` env vars
    (``AWS_ENDPOINT_URL`` / ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``,
    optional ``AWS_DEFAULT_REGION``) — the names Railway's bucket "AWS SDK" preset
    injects and boto3 reads by convention. Any S3-compatible object store works.

    Not exercised by any test — those inject ``FakeS3Client`` instead (see
    scripts/tests/test_corpus_loader.py). Only used by the operator runbook
    that runs the one-time corpus upload.
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
    return _NotFoundIsNoneAdapter(raw)


class _NotFoundIsNoneAdapter:
    """Wraps a raw boto3 S3 client so ``head_object`` returns ``None`` on a
    missing key (matching the ``S3Client`` protocol) instead of raising
    botocore's ``ClientError``."""

    def __init__(self, boto_client):
        self._client = boto_client

    def head_object(self, *, Bucket: str, Key: str) -> dict | None:
        from botocore.exceptions import ClientError

        try:
            return self._client.head_object(Bucket=Bucket, Key=Key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def put_object(self, **kwargs: object) -> dict:
        return self._client.put_object(**kwargs)
