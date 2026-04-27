"""Ingredient string parser. Pure functions, no I/O.

See docs/superpowers/specs/2026-04-25-ingredient-parser-design.md for the
parser ladder. Bump PARSER_VERSION whenever any rule's behavior changes
(including unit-table edits, regex changes, new rules).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

from ingredients.units import (
    canonicalize_unit,
    canonicalize_count_noun,
    canonicalize_qty_noun,
    canonicalize_known_noun,
    UNIT_ALIASES,
)

PARSER_VERSION = "v7"

# Pattern used to detect concatenated multi-ingredient rows in the candidate
# name produced by _try_qty_unit. If the name contains an embedded quantity
# followed by a known unit (e.g. "amaro3 oz ...") it's a concatenation artifact
# and we must abstain rather than produce a garbled parse.
# Built from the full UNIT_ALIASES table so it stays in sync automatically.
# Sorted longest-first to avoid early truncation in alternation.
_UNIT_ALTERNATION = "|".join(
    re.escape(k) for k in sorted(UNIT_ALIASES, key=len, reverse=True)
)
# Concat-row guard: a *letter* directly followed by `<digit>+ <unit>` is the
# scraper-artifact giveaway (`Amaro3 oz Lambrusco`, `Rosé1 oz club soda`).
# Plain `<digit>+ <unit>` without a leading letter is a legitimate annotation
# (`750 ml bottle of vodka`, `(approximately 1 1/2 cups)`) and must not fire.
_CONCAT_RE = re.compile(
    rf"[a-zA-Z]\d+\s*(?:{_UNIT_ALTERNATION})\b", re.IGNORECASE
)
_PAREN_RE = re.compile(r"\([^)]*\)")
# Hyphen-attached size annotation seen on container rows
# (`1-ounce`, `750-ml`, `12-inch`). The qty regex already grabbed the leading
# digits, so this is what's *left* on the rest after qty extraction.
_HYPHEN_SIZE_RE = re.compile(
    r"\b\d+[ -](?:ounce|oz|ml|cl|l|inch|cm|mm|gram|g|kg|pound|lb|pint|quart)\b",
    re.IGNORECASE,
)


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

# Common units that recipe writers may glue to a qty with a hyphen
# (`1/2-ounce`, `1-pound`). Conservative whitelist: real volume/weight
# units, not annotation-only ones like `inch`/`cm` (which describe a
# different attribute, e.g. wheel thickness, not the row's quantity).
_HYPHEN_QTY_UNIT_RE = re.compile(
    r"^(\d+(?:\.\d+)?(?:/\d+)?(?:\s+\d+/\d+)?)-"
    r"(?=(?:ounces?|oz|milliliters?|ml|cl|liters?|litres?|"
    r"teaspoons?|tsp|tablespoons?|tbsp|cups?|"
    r"pints?|quarts?|gallons?|pounds?|lbs?|grams?|kilograms?|kg|g)\b)",
    re.IGNORECASE,
)


def pre_clean(s: str) -> str:
    """Normalize a raw ingredient string for downstream rule matching.

    Idempotent. Lossy only in trivial ways (whitespace, trailing punct).
    The original string is preserved in ParseResult.raw_text for audit.
    """
    if s is None:
        return ""
    # Decode HTML entities first (`1&frasl;2` → `1⁄2`, `&amp;` → `&`, etc.)
    # so downstream fraction/whitespace rules see real characters.
    if "&" in s:
        s = html.unescape(s)
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
    # Normalize hyphen-attached qty+unit (`1/2-ounce gin` → `1/2 ounce gin`).
    # Only fires when the string starts with `<numeric>-<unit-alias>` — so
    # `1 750-ml bottle …` is left alone (the leading qty is `1`, then a
    # space, not a dash).
    s = _HYPHEN_QTY_UNIT_RE.sub(r"\1 ", s)
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
# Range separators: `to`, `or`, or hyphen (`1-2`, `1 to 2`, `3 or 4`).
_QTY_RE = re.compile(rf"^(?P<a>{_NUM_ATOM})(?:\s*(?:to|or|-)\s*(?P<b>{_NUM_ATOM}))?")


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
    # Strip a leading unit-position qualifier (`1 heaping tablespoon`,
    # `1 scant cup`). The qualifier only modifies the magnitude of the
    # unit; v1 doesn't surface it (modifier=None).
    leading_word = rest.split(" ", 1)[0].lower()
    if leading_word in _UNIT_QUALIFIERS:
        rest = rest.split(" ", 1)[1].lstrip() if " " in rest else ""
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
    # Concatenated-row guard: if the candidate name contains an embedded
    # quantity+unit token (e.g. "amaro3 oz lambrusco..."), it's a scraper
    # artifact and we must abstain. Parenthesized text is treated as benign
    # annotation (`(3 parts sugar to 4 parts ginger juice)` is a recipe
    # ratio inside one ingredient, not a smuggled second ingredient).
    if _CONCAT_RE.search(_PAREN_RE.sub(" ", name_part)):
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


_QUALIFIERS = (
    "fresh", "dried", "whole",
    # size / ripeness adjectives that recipe writers stack between qty and noun
    # (`1 large lemon`, `2 ripe peaches`, `3 small strawberries`).
    "large", "small", "medium", "ripe", "thin",
    # color modifiers seen in the histogram (`4 black tea bags`, `4 green olives`).
    "black", "green",
    # preparation adjectives that don't change ingredient identity
    # (`Crushed ice`, `Chopped chocolate`, `Sliced strawberries`,
    # `Freshly grated nutmeg`, `Chilled orange soda`).
    "crushed", "chopped", "sliced", "freshly", "chilled",
    "frozen", "candied", "pickled", "toasted", "sugared", "grated",
    "hulled", "pitted", "seedless", "finely", "lightly",
)

# Qualifiers that sit between qty and unit (`1 heaping tablespoon`,
# `1 scant cup`, `1 mounded teaspoon`). Distinct from `_QUALIFIERS`,
# which sits between qty and noun.
_UNIT_QUALIFIERS = ("heaping", "scant", "mounded")


def _try_count_noun(cleaned: str, raw: str) -> ParseResult | None:
    """Match `<qty> [qualifier]? <name_tokens>+ <count_noun>` (tail position)
    or `<qty> [qualifier]? <count_noun> <name_tokens>+` (head position).

    Tail wins when both ends would match. Strings whose count noun would
    leave an empty name (e.g. '1 egg white') still abstain — empty names
    produce no useful structure.
    """
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:].lstrip().lower()
    if not rest:
        return None

    # Annotated rows (parens, hyphenated container size, or comma-suffix
    # prep notes) belong to qty_annotated_name. Without these gates,
    # comma-suffix rows like `8 lemon wheels, for garnish` lose the tail
    # match (the comma sticks to `wheels,`) and head-position fires on
    # `lemon` instead — yielding the inverted unit=lemon, name="wheels…".
    if "(" in rest or "," in rest or _HYPHEN_SIZE_RE.search(rest):
        return None

    tokens = rest.split()
    # Strip leading qualifiers — repeatedly, so `2 freshly sliced pears`
    # peels off both `freshly` and `sliced` before the noun match.
    while tokens and tokens[0] in _QUALIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None

    # Empty-name guard: if the full remaining text canonicalizes as a
    # known *qty* noun (`1 egg white`, `1 lemon`), we'd produce an empty
    # name. Abstain so qty_known_noun can pick it up with name=<canonical>.
    if canonicalize_qty_noun(" ".join(tokens)) is not None:
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

    # Head-position fallback: `<qty> <count_noun> <name_tokens>+`
    # (e.g. `1.5 cloves garlic`, `3 scoop vanilla ice cream`,
    # `1 orange half-wheel`). Tail check above already declined.
    for head_words in (2, 1):
        if len(tokens) < head_words + 1:
            continue
        head = " ".join(tokens[:head_words])
        canon = canonicalize_count_noun(head)
        if canon is None:
            continue
        name_part = " ".join(tokens[head_words:]).strip()
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


def _try_qty_known_noun(cleaned: str, raw: str) -> ParseResult | None:
    """Match `<qty> [qualifier]? <known_noun>` where the noun is the
    entire remaining phrase. Emits unit="each", name=<canonical>.

    `each` is the count-of-whole-items unit — semantically equivalent
    to "1 (one) lemon" rather than "1 oz lemon" or "1 wedge lemon".
    Distinct from `unit=None` (used for unstructured rows in
    qty_annotated_name where we don't know the unit).

    Fires when count_noun's empty-name guard would otherwise abstain
    (`1 lemon`, `1 banana`, `1 star anise`, `1 egg white`).
    """
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:].lstrip().lower()
    if not rest:
        return None
    tokens = rest.split()
    while tokens and tokens[0] in _QUALIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None
    canon = canonicalize_qty_noun(" ".join(tokens))
    if canon is None:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="qty_known_noun",
        amount=amount,
        amount_max=amount_max,
        unit="each",
        name=canon,
    )


def _try_qty_annotated_name(cleaned: str, raw: str) -> ParseResult | None:
    """Catch-all for `<qty> <messy_phrase>` where the phrase carries
    container/prep annotation (parens, commas, hyphenated size). Emits
    unit=None, name=<full rest> so the annotation is preserved verbatim.

    Discipline: only fires when there's an annotation signal, and only
    when a paren-aware concat-row check passes (so true multi-ingredient
    junk like `0.5 oz Amaro3 oz Lambrusco` still abstains).
    """
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:].lstrip()
    if not rest:
        return None
    has_signal = (
        "(" in rest
        or "," in rest
        or "-" in rest
        or _HYPHEN_SIZE_RE.search(rest) is not None
    )
    if not has_signal:
        return None
    # If rest starts with a known unit alias, qty_unit was the rule responsible
    # — and if it didn't claim the row, the input was malformed (concat guard,
    # empty name, etc.). Don't shove the unit into the name as a consolation.
    rest_lower = rest.lower()
    leading = rest_lower.split(" ", 3)
    for n in (3, 2, 1):
        if len(leading) > n and canonicalize_unit(" ".join(leading[:n])):
            return None
    # Concat-row guard, but treat parenthesized text as benign annotation
    # rather than a smuggled second ingredient.
    no_parens = _PAREN_RE.sub(" ", rest).lower()
    if _CONCAT_RE.search(no_parens):
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="qty_annotated_name",
        amount=amount,
        amount_max=amount_max,
        unit=None,
        name=rest.lower(),
    )


# Lexical-qty heads — words that act as a qty *and* an imprecise unit when
# they sit at the start of a no-numeric-qty row (`Pinch X`, `Splash X`,
# `Dash X`). Subset of UNIT_ALIASES. Multi-word entries (`bar spoon`) are
# omitted; the head detection only checks 1- and 2-token spans.
_LEXICAL_QTY_HEADS = (
    "pinch", "pinches", "dash", "dashes", "splash", "splashes",
    "drop", "drops", "sprinkle", "sprinkles", "grind", "grinds",
    "handful", "handfuls", "knob", "knobs",
    "dropper", "droppers", "dropperful", "dropperfuls",
    "barspoon", "barspoons",
)


def _try_lexical_qty(cleaned: str, raw: str) -> ParseResult | None:
    """Match `<lexical_qty> <name>` for rows with no numeric qty
    (`Pinch ground cinnamon`, `Splash lemon-lime soda`, `Dash bitters`).
    Emits amount=None, unit=<canon>, name=<rest>.
    """
    if parse_quantity(cleaned) is not None:
        return None
    tokens = cleaned.split()
    if not tokens:
        return None
    head = tokens[0].lower()
    if head not in _LEXICAL_QTY_HEADS:
        return None
    canon = canonicalize_unit(head)
    if canon is None:
        return None
    name = " ".join(tokens[1:]).strip().lower()
    # `Pinch of salt` / `Splash of lime juice` — drop the connector "of".
    if name.startswith("of "):
        name = name[3:].strip()
    if not name:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="lexical_qty",
        amount=None,
        amount_max=None,
        unit=canon,
        name=name,
    )


def _try_no_qty_known_noun(cleaned: str, raw: str) -> ParseResult | None:
    """Match a no-qty row whose first 1-3 tokens (after stripping a leading
    qualifier) include a known noun. Emits amount=None, unit=None,
    name=<full cleaned text> so the prep/garnish phrase is preserved.

    Recovers `Ice`, `Crushed ice`, `Lemon wheels, for garnish`,
    `Soda water`, `Mint sprigs, for garnish` — anything no-qty that
    anchors on a recognized ingredient noun.
    """
    if parse_quantity(cleaned) is not None:
        return None
    cleaned_lower = cleaned.lower()
    # Token list with punctuation stripped, so `lemon,` matches `lemon`.
    tokens = [t for t in re.split(r"[^\w'’\-]+", cleaned_lower) if t]
    if not tokens:
        return None
    # Strip a leading noun-qualifier (fresh/large/crushed/etc.).
    if tokens[0] in _QUALIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None
    # Look for a known noun in the first 3 tokens, as 1-word or 2-word spans.
    head_window = tokens[:3]
    found = False
    for n in (2, 1):
        for start in range(len(head_window) - n + 1):
            span = " ".join(head_window[start : start + n])
            if canonicalize_known_noun(span) is not None:
                found = True
                break
        if found:
            break
    if not found:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="no_qty_known_noun",
        amount=None,
        amount_max=None,
        unit=None,
        name=cleaned_lower,
    )


_RULES = [
    _try_garnish_prefix,
    _try_topup,
    _try_qty_unit,
    _try_count_noun,
    _try_qty_known_noun,
    _try_qty_annotated_name,
    _try_lexical_qty,
    _try_no_qty_known_noun,
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
