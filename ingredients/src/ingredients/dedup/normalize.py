"""Canonical normalization for cocktail-name lookups.

Wraps mapping.normalize.normalize_name (lowercase + whitespace) and adds
cocktail-name specific cleanup: stop-word stripping ('the', 'best',
'classic', 'cocktail', 'recipe'), parenthetical removal, hyphen→space
folding. Stop-words are stripped wherever they appear as standalone tokens;
embedded stop-words inside multi-word names (e.g. 'the' in 'Death in the
Afternoon') are also stripped in this v1 implementation.

This is the function the alias_layer keys against: a cocktail_aliases.alias
row is itself the output of this function applied to some raw title.
"""

from __future__ import annotations

import re

from ingredients.mapping.normalize import normalize_name as _base_normalize

# Tokens stripped wherever they appear as standalone words.
_STOP_WORDS = frozenset({
    "the", "a", "an",
    "best", "perfect", "classic", "ultimate", "easy", "simple", "quick",
    "cocktail", "recipe",
    "how", "to", "make", "for",
})

_PAREN = re.compile(r"\([^)]*\)")
_NON_WORD_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_cocktail_name(raw: str | None) -> str:
    if raw is None:
        return ""
    s = _base_normalize(raw)
    if not s:
        return ""
    # Drop parentheticals.
    s = _PAREN.sub(" ", s)
    # Replace non-word punctuation with whitespace; preserve word characters.
    s = _NON_WORD_PUNCT.sub(" ", s)
    # Tokenize, strip stop-words, rejoin.
    tokens = [t for t in s.split() if t and t not in _STOP_WORDS]
    return _WS.sub(" ", " ".join(tokens)).strip()
