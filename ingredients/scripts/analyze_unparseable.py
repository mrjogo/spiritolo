"""Bucket unparseable recipe_ingredients rows by likely cause.

Run from repo root:
    cd ingredients && uv run python scripts/analyze_unparseable.py
    cd ingredients && uv run python scripts/analyze_unparseable.py --site punch
    cd ingredients && uv run python scripts/analyze_unparseable.py --samples 5

Read-only. No parser/schema changes. Heuristic buckets are mutually
exclusive: each row falls into the first matching bucket.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict

from ingredients.db import IngredientsDatabase
from ingredients.parser import parse_quantity, pre_clean
from ingredients.units import UNIT_ALIASES, COUNT_NOUN_ALIASES


_HEADER_RE = re.compile(r"^(for the\b|to (make|serve|garnish)\b)", re.IGNORECASE)
_PARENS_ONLY_RE = re.compile(r"^\(.+\)$")
_NOTE_RE = re.compile(r"\b(see (note|recipe|below)|to taste|optional)\b", re.IGNORECASE)
_LEADING_QUALIFIER_RE = re.compile(
    r"^(a|an|one|two|three|four|five|six|seven|eight|nine|ten|some|few|several|"
    r"plenty|lots|handful|pinch)\b",
    re.IGNORECASE,
)
_BARE_GARNISH_RE = re.compile(r"^(garnish|to garnish|for garnish)\b", re.IGNORECASE)


def _bucket(raw: str) -> tuple[str, str]:
    """Return (bucket_key, normalized_cleaned). First match wins."""
    cleaned = pre_clean(raw)
    if not cleaned:
        return "empty_after_clean", ""
    if _HEADER_RE.match(cleaned):
        return "section_header", cleaned
    if _PARENS_ONLY_RE.match(cleaned):
        return "parenthesized_only", cleaned
    if _BARE_GARNISH_RE.match(cleaned):
        return "bare_garnish_no_colon", cleaned
    if _NOTE_RE.search(cleaned):
        return "note_or_to_taste", cleaned

    qty = parse_quantity(cleaned)
    if qty is None:
        if _LEADING_QUALIFIER_RE.match(cleaned):
            return "word_quantity_no_digits", cleaned
        if len(cleaned) > 120:
            return "no_quantity_long_prose", cleaned
        return "no_leading_quantity", cleaned

    _amt, _amt_max, end = qty
    rest = cleaned[end:].lstrip().lower()
    if not rest:
        return "quantity_only_no_unit_or_name", cleaned

    first_token = rest.split(" ", 1)[0]
    first_two = " ".join(rest.split(" ", 2)[:2])
    first_three = " ".join(rest.split(" ", 3)[:3])

    has_unit_alias = any(
        cand in UNIT_ALIASES
        for cand in (first_token, first_two, first_three)
    )
    has_count_noun_alias = any(
        cand in COUNT_NOUN_ALIASES
        for cand in (first_token, first_two)
    )

    if has_unit_alias:
        # qty_unit matched the prefix but the rule still rejected it — almost
        # certainly the concat-row guard, since the only other rejection is an
        # empty name (already covered above).
        return "qty_unit_concat_guard", cleaned

    # No unit alias; look for an end-of-string count noun (the count_noun rule
    # tries 1- and 2-token tails).
    tokens = rest.split()
    tail_1 = tokens[-1] if tokens else ""
    tail_2 = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""
    end_count_noun = (
        tail_1 in COUNT_NOUN_ALIASES or tail_2 in COUNT_NOUN_ALIASES
    )
    if end_count_noun:
        return "count_noun_empty_name", cleaned
    if has_count_noun_alias:
        # Count noun is at the head, not the tail. v1 abstains by design.
        return "count_noun_head_position", cleaned

    return "qty_then_unknown_unit", cleaned


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bucket unparseable recipe_ingredients rows.",
    )
    parser.add_argument("--site", default=None, help="Restrict to one site.")
    parser.add_argument(
        "--parser-version", default=None,
        help="Restrict to rows at this parser_version (default: all versions).",
    )
    parser.add_argument(
        "--samples", type=int, default=3,
        help="Number of sample raw_text strings to print per bucket.",
    )
    parser.add_argument(
        "--per-site", action="store_true",
        help="Also print a per-site breakdown.",
    )
    args = parser.parse_args()

    db = IngredientsDatabase()
    try:
        clauses = ["ri.parse_status = 'unparseable'"]
        params: list = []
        if args.site:
            clauses.append("r.site = %s")
            params.append(args.site)
        if args.parser_version:
            clauses.append("ri.parser_version = %s")
            params.append(args.parser_version)
        sql = f"""
            select r.site, ri.raw_text
            from recipe_ingredients ri
            join recipes r on r.id = ri.recipe_id
            where {' and '.join(clauses)}
        """
        rows = db.conn.execute(sql, params).fetchall()
    finally:
        db.close()

    total = len(rows)
    if total == 0:
        print("no unparseable rows match the filter")
        return 0

    overall: Counter[str] = Counter()
    per_site: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[str]] = defaultdict(list)

    for site, raw in rows:
        if raw is None:
            continue
        bucket, _cleaned = _bucket(raw)
        overall[bucket] += 1
        per_site[site][bucket] += 1
        if len(samples[bucket]) < args.samples:
            samples[bucket].append(raw)

    print(f"--- Unparseable buckets ({total} rows) ---")
    width = max(len(k) for k in overall) if overall else 0
    for bucket, count in overall.most_common():
        pct = 100.0 * count / total
        print(f"  {bucket:<{width}}  {count:>7}  ({pct:5.1f}%)")
        for s in samples[bucket]:
            short = s if len(s) <= 100 else s[:97] + "..."
            print(f"      e.g. {short!r}")

    if args.per_site:
        print()
        print("--- Per-site (top 5 buckets each) ---")
        for site in sorted(per_site):
            site_total = sum(per_site[site].values())
            print(f"  {site}: {site_total} unparseable")
            for bucket, count in per_site[site].most_common(5):
                pct = 100.0 * count / site_total
                print(f"    {bucket:<{width}}  {count:>7}  ({pct:5.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
