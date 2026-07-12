"""Content-addressed R2 object keys for the HTML corpus.

Deliberately NOT canonicalized: a key is exactly ``sha256(url)``. The loader
never normalizes a url (trailing slash, scheme, ...) before hashing it — the
caller owns any normalization, so the same url always maps to the same key
and different urls never collide (see docs/redesign.md WS-B20).
"""
from __future__ import annotations

import hashlib


def sha256_key(url: str) -> str:
    """Return the R2 object key for ``url``."""
    return hashlib.sha256(url.encode()).hexdigest()
