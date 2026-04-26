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


# Atomic numeric token: integer, decimal, fraction, or mixed number.
# Mixed and fraction must come BEFORE plain integer in alternations.
# Fraction denominators are [1-9]\d* — forbids zero (avoids divide-by-zero
# downstream) and forbids leading-zero denominators that wouldn't be valid.
_NUM_ATOM = r"(?:\d+\s+\d+/[1-9]\d*|\d+/[1-9]\d*|\d+(?:\.\d+)?)"
_QTY_RE = re.compile(rf"^(?P<a>{_NUM_ATOM})(?:\s*(?:to|-)\s*(?P<b>{_NUM_ATOM}))?")


def _atom_to_float(token: str) -> float:
    token = token.strip()
    if " " in token:
        whole, frac = token.split(None, 1)
        num, den = frac.split("/")
        return float(whole) + float(num) / float(den)
    if "/" in token:
        num, den = token.split("/")
        return float(num) / float(den)
    return float(token)


def parse_quantity(s: str) -> tuple[float, float | None, int] | None:
    """Match a leading quantity in s.

    Returns (amount, amount_max, end_index) where end_index is the position
    in s immediately after the matched quantity. Returns None when s does
    not start with a recognizable quantity.

    amount_max is non-None only for ranges ('1/2 to 3/4', '1-2').
    """
    m = _QTY_RE.match(s)
    if not m:
        return None
    a = _atom_to_float(m.group("a"))
    b = _atom_to_float(m.group("b")) if m.group("b") else None
    return a, b, m.end()


_GARNISH_PREFIX_RE = re.compile(r"^garnish\s*:\s*(?P<name>.+)$", re.IGNORECASE)


def _try_garnish_prefix(cleaned: str, raw: str) -> ParseResult | None:
    m = _GARNISH_PREFIX_RE.match(cleaned)
    if not m:
        return None
    name = m.group("name").strip().lower()
    if not name:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="garnish_prefix",
        name=name,
    )


_TOPUP_RE = re.compile(r"^top up with\s+(?P<name>.+)$", re.IGNORECASE)


def _try_topup(cleaned: str, raw: str) -> ParseResult | None:
    m = _TOPUP_RE.match(cleaned)
    if not m:
        return None
    name = m.group("name").strip().lower()
    if not name:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="topup",
        name=name,
    )


_RULES = [
    _try_garnish_prefix,
    _try_topup,
]


def parse(raw: str, site: str | None = None) -> ParseResult:
    """Apply the parser ladder to `raw`. Returns ParseResult; never raises.

    `site` is informational only; rules may use it to dispatch quirks but
    must not relax strictness based on it.
    """
    cleaned = pre_clean(raw)
    if not cleaned:
        return ParseResult(raw_text=raw, parse_status="unparseable")
    for rule in _RULES:
        result = rule(cleaned, raw)
        if result is not None:
            return result
    return ParseResult(raw_text=raw, parse_status="unparseable")
