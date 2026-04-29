"""Canonical normalization for ingredient name lookups.

Kept narrow on purpose: lowercase + whitespace cleanup. Punctuation and
diacritics are preserved because form-node distinctions ('lemon, juiced')
and alias seeds for accented strings depend on them.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if raw is None:
        return ""
    return _WS.sub(" ", raw.strip().lower())
