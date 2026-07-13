"""Mint kebab-case drink slugs from ``recipe_clusters.canonical_name``.

The slug is the drink-level join key — owned by Spiritolo, joined on by Barbot.
It must satisfy RecipeGF's id-slug grammar (``^[a-z0-9]+(?:-[a-z0-9]+)*$``), the
same pattern the id authority uses per-label. We derive it, then let RecipeGF's
own ``is_valid_recipe_id`` be the final gate downstream (in ``converter``) — so
this module and the RecipeGF grammar can never silently drift.
"""

from __future__ import annotations

import re
import unicodedata

# The kebab-slug grammar for a single id label, mirrored from RecipeGF's
# RECIPE_ID_PATTERN (the slug segment). Asserted against RecipeGF in tests.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(text: str) -> str:
    """Best-effort kebab-case reduction: strip accents, lowercase, collapse any
    run of non-``[a-z0-9]`` into a single hyphen, trim leading/trailing hyphens.

    Deterministic and idempotent (``slugify(slugify(x)) == slugify(x)``). May
    return ``""`` for input with no alphanumerics — callers must handle that.
    """
    # Decompose accents (é → e), drop combining marks and non-ASCII.
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    return hyphenated.strip("-")


def is_valid_slug(slug: str) -> bool:
    """True iff ``slug`` matches the kebab-case id-slug grammar."""
    return _SLUG_RE.match(slug) is not None


def mint_slug(canonical_name: str | None) -> str | None:
    """Derive a valid kebab-case slug from a cluster's canonical name.

    Returns ``None`` when no valid slug can be produced (empty/whitespace/
    punctuation-only name) — the caller routes that to propose→review rather
    than emitting an invalid id.
    """
    if not canonical_name:
        return None
    slug = slugify(canonical_name)
    if not slug or not is_valid_slug(slug):
        return None
    return slug
