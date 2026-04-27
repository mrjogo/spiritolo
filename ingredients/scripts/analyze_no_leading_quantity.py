"""For rows that fall in the no_leading_quantity bucket, tally the first
token of the cleaned string. Helps spot dominant phrasings that need new
no-qty rules (`Float X`, `Top with X`, `Garnish: X`, bare-noun ingredients).

Run from repo root:
    cd ingredients && uv run python scripts/analyze_no_leading_quantity.py
    cd ingredients && uv run python scripts/analyze_no_leading_quantity.py --site punch
    cd ingredients && uv run python scripts/analyze_no_leading_quantity.py --top 50
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

from ingredients.db import IngredientsDatabase
from ingredients.parser import parse_quantity, pre_clean

# Mirror the gating regexes from analyze_unparseable.py.
_HEADER_RE = re.compile(r"^(for the\b|to (make|serve|garnish)\b)", re.IGNORECASE)
_PARENS_ONLY_RE = re.compile(r"^\(.+\)$")
_NOTE_RE = re.compile(r"\b(see (note|recipe|below)|to taste|optional)\b", re.IGNORECASE)
_LEADING_QUALIFIER_RE = re.compile(
    r"^(a|an|one|two|three|four|five|six|seven|eight|nine|ten|some|few|several|"
    r"plenty|lots|handful|pinch)\b",
    re.IGNORECASE,
)
_BARE_GARNISH_RE = re.compile(r"^(garnish|to garnish|for garnish)\b", re.IGNORECASE)


def _first_word_or_none(raw: str) -> str | None:
    """Return the lowercased first token of `cleaned`, only when the row
    would fall into the no_leading_quantity bucket."""
    cleaned = pre_clean(raw)
    if not cleaned:
        return None
    if _HEADER_RE.match(cleaned) or _PARENS_ONLY_RE.match(cleaned):
        return None
    if _BARE_GARNISH_RE.match(cleaned) or _NOTE_RE.search(cleaned):
        return None

    qty = parse_quantity(cleaned)
    if qty is not None:
        return None  # rows with a leading qty go to other buckets

    if _LEADING_QUALIFIER_RE.match(cleaned):
        return None  # word_quantity_no_digits
    if len(cleaned) > 120:
        return None  # no_quantity_long_prose

    return cleaned.split(" ", 1)[0].lower()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--site", default=None)
    p.add_argument("--parser-version", default=None)
    p.add_argument("--top", type=int, default=40)
    p.add_argument(
        "--samples", type=int, default=2,
        help="Sample raw_text strings to print per word.",
    )
    args = p.parse_args()

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

    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    bucket_total = 0
    for _site, raw in rows:
        if raw is None:
            continue
        word = _first_word_or_none(raw)
        if word is None:
            continue
        bucket_total += 1
        counts[word] += 1
        bag = samples.setdefault(word, [])
        if len(bag) < args.samples:
            bag.append(raw)

    print(
        f"--- no_leading_quantity: first-word frequency "
        f"({bucket_total} rows, {len(counts)} distinct words) ---"
    )
    width = max((len(w) for w, _ in counts.most_common(args.top)), default=0)
    cum = 0
    for word, count in counts.most_common(args.top):
        cum += count
        pct = 100.0 * count / bucket_total
        cum_pct = 100.0 * cum / bucket_total
        print(f"  {word:<{width}}  {count:>5}  ({pct:5.1f}%)  cum {cum_pct:5.1f}%")
        for s in samples[word]:
            short = s if len(s) <= 100 else s[:97] + "..."
            print(f"      e.g. {short!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
