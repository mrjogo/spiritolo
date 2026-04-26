"""Ingredient string parser. Pure functions, no I/O.

See docs/superpowers/specs/2026-04-25-ingredient-parser-design.md for the
parser ladder. Bump PARSER_VERSION whenever any rule's behavior changes
(including unit-table edits, regex changes, new rules).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ingredients.units import canonicalize_unit, canonicalize_count_noun

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


def _try_qty_unit(cleaned: str, raw: str) -> ParseResult | None:
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:]
    if not rest.startswith(" "):
        return None
    rest = rest.lstrip()
    if not rest:
        return None
    # Greedy match the longest unit alias that prefixes the remaining text.
    # Multi-word aliases (e.g. 'fluid ounce', 'fl oz') must be tried before
    # single-word aliases.
    unit_canon = None
    name_start = -1
    for alias_len_words in (3, 2, 1):
        tokens = rest.split(" ", alias_len_words)
        if len(tokens) <= alias_len_words:
            continue
        candidate_alias = " ".join(tokens[:alias_len_words])
        canon = canonicalize_unit(candidate_alias)
        if canon is None:
            continue
        # Prefer the longest matching alias by trying alias_len_words=3 first.
        unit_canon = canon
        name_start = len(candidate_alias)
        break
    if unit_canon is None:
        return None
    name_part = rest[name_start:].lstrip().lower()
    name_part = re.sub(r"\s+", " ", name_part).strip()
    if not name_part:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="qty_unit",
        amount=amount,
        amount_max=amount_max,
        unit=unit_canon,
        name=name_part,
    )


_QUALIFIERS = ("fresh", "dried", "whole")


def _try_count_noun(cleaned: str, raw: str) -> ParseResult | None:
    """Match `<qty> [fresh|dried|whole]? <name_tokens>* <count_noun>` OR
    `<qty> [fresh|dried|whole]? <count_noun> <name_tokens>+`.

    The count noun must be in COUNT_NOUN_ALIASES. Strings with no count noun
    abstain. Strings with no name (e.g. '1 egg white') also abstain — empty
    names produce no useful structure.
    """
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:].lstrip().lower()
    if not rest:
        return None

    tokens = rest.split()
    # Strip a leading qualifier if present (drop it; modifier=None for v1).
    if tokens and tokens[0] in _QUALIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None

    # Try count noun at end-of-string first (most common: '3 fresh basil leaves').
    # Multi-word count nouns ('egg white') need a 2-token tail check.
    for tail_words in (2, 1):
        if len(tokens) < tail_words + 1:
            continue
        tail = " ".join(tokens[-tail_words:])
        canon = canonicalize_count_noun(tail)
        if canon is None:
            continue
        name_tokens = tokens[:-tail_words]
        name_part = " ".join(name_tokens).strip()
        if not name_part:
            return None
        return ParseResult(
            raw_text=raw,
            parse_status="parsed",
            parser_rule="count_noun",
            amount=amount,
            amount_max=amount_max,
            unit=canon,
            name=name_part,
        )
    return None


_RULES = [
    _try_garnish_prefix,
    _try_topup,
    _try_qty_unit,
    _try_count_noun,
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
