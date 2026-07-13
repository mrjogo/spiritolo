"""Content-addressed R2 key derivation for the HTML corpus.

Keys are sha256(url) — stable and url-sensitive on purpose: the loader never
canonicalizes a url before hashing it, so the caller owns any normalization.
"""
from __future__ import annotations

import hashlib

from corpus_loader.keys import sha256_key


def test_key_is_sha256_of_url():
    key = sha256_key("https://a/b")
    assert key == hashlib.sha256(b"https://a/b").hexdigest()
    assert len(key) == 64
    assert key == key.lower()
    assert all(c in "0123456789abcdef" for c in key)


def test_key_stable_across_calls():
    url = "https://example.com/cocktails/negroni"
    assert sha256_key(url) == sha256_key(url)


def test_key_url_sensitive():
    # No canonicalization: trailing slash and scheme differences must yield
    # different keys.
    assert sha256_key("https://example.com/a") != sha256_key("https://example.com/a/")
    assert sha256_key("http://example.com/a") != sha256_key("https://example.com/a")
