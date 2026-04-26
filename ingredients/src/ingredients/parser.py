"""Ingredient string parser. Pure functions, no I/O.

See docs/superpowers/specs/2026-04-25-ingredient-parser-design.md for the
parser ladder. Bump PARSER_VERSION whenever any rule's behavior changes
(including unit-table edits, regex changes, new rules).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PARSER_VERSION = "v1"


@dataclass
class ParseResult:
    raw_text: str
    parse_status: str  # 'parsed' | 'unparseable'
    parser_rule: str | None = None
    amount: float | None = None
    amount_max: float | None = None
    unit: str | None = None
    name: str | None = None
    modifier: str | None = None  # v1: always None


_UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4",
    "⅐": "1/7", "⅑": "1/9", "⅒": "1/10",
    "⅓": "1/3", "⅔": "2/3",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}

_TRIM_PUNCT = ",.;:"


def pre_clean(s: str) -> str:
    """Normalize a raw ingredient string for downstream rule matching.

    Idempotent. Lossy only in trivial ways (whitespace, trailing punct).
    The original string is preserved in ParseResult.raw_text for audit.
    """
    if s is None:
        return ""
    # Replace unicode fraction chars with ASCII fractions BEFORE NFKC,
    # because NFKC expands e.g. ½ (U+00BD) → 1⁄2 (U+2044 fraction slash).
    for u, ascii_frac in _UNICODE_FRACTIONS.items():
        if u in s:
            s = s.replace(u, ascii_frac)
    # NFKC: collapses non-breaking spaces, normalizes width forms.
    s = unicodedata.normalize("NFKC", s)
    # Replace any remaining U+2044 FRACTION SLASH with plain ASCII slash.
    s = s.replace("⁄", "/")
    # Collapse all whitespace runs to single space; strip outer.
    s = re.sub(r"\s+", " ", s).strip()
    # Strip trailing junk punctuation.
    while s and s[-1] in _TRIM_PUNCT:
        s = s[:-1].rstrip()
    # And leading.
    while s and s[0] in _TRIM_PUNCT:
        s = s[1:].lstrip()
    return s
