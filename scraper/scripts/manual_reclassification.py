"""Manual reclassifications — a persistent record and replayable script.

Each entry is a named `(SQL, label)` pair. Running an entry updates every row
matched by the SQL to the target label and appends an audit row with
`prompt_version='manual'`. Entries are idempotent: rows already at the target
label are skipped, so re-running is safe and cheap.

When a human decides the classifier should be corrected for a given URL
pattern, add a new entry here with enough comment context to explain WHY the
human call was made. Over time this file is both the script that applies the
corrections and the log of what has been corrected.

Usage:
  uv run python -m scripts.manual_reclassification                   # run all entries
  uv run python -m scripts.manual_reclassification KEY1 KEY2         # run selected entries
  uv run python -m scripts.manual_reclassification --list            # list entries
  uv run python -m scripts.manual_reclassification --dry-run KEY1    # report counts only
  uv run python -m scripts.manual_reclassification --null KEY1       # NULL content_type for matches
"""

import argparse
import json
import sys
from pathlib import Path

from scraper.src.db import Database

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "scraper.db"


# key → (SQL SELECT returning at minimum `id`, target label)
#
# The SQL is wrapped by the runner with an idempotency filter against
# `pages.content_type`, so entries only need to identify rows to reclassify —
# not worry about skipping already-corrected rows.
RECLASSIFICATIONS: dict[str, tuple[str, str]] = {
    # Diffordsguide /encyclopedia/*/{bars,books,bws,cocktails,events,people,
    # productsandservices,simons-blog}/ — drink-industry editorial that isn't a
    # pure drink article (venue/book/product/person references, competitions,
    # editorial blog). New label `likely_cocktail_adjacent` introduced to cover
    # these so the classifier stops shoehorning them into `likely_drink_article`.
    "diffordsguide_encyclopedia_cocktail_adjacent": (
        """
        SELECT id, url FROM pages
        WHERE site='diffordsguide' AND (
          url LIKE '%/encyclopedia/%/bars/%' OR
          url LIKE '%/encyclopedia/%/books/%' OR
          url LIKE '%/encyclopedia/%/bws/%' OR
          url LIKE '%/encyclopedia/%/cocktails/%' OR
          url LIKE '%/encyclopedia/%/events/%' OR
          url LIKE '%/encyclopedia/%/people/%' OR
          url LIKE '%/encyclopedia/%/productsandservices/%' OR
          url LIKE '%/encyclopedia/%/simons-blog/%'
        )
        """,
        "likely_cocktail_adjacent",
    ),
    # Diffordsguide /encyclopedia/*/{company-info,competitions}/ — site-meta and
    # cocktail-competition pages; no editorial value, not drink content.
    "diffordsguide_encyclopedia_junk": (
        """
        SELECT id, url FROM pages
        WHERE site='diffordsguide' AND (
          url LIKE '%/encyclopedia/%/company-info/%' OR
          url LIKE '%/encyclopedia/%/competitions/%'
        )
        """,
        "likely_junk",
    ),
    # Foodnetwork /videos/ — video pages with no extractable recipe text.
    # Technique videos and show clips were leaking into food_article/food_recipe
    # under the v4 prompt; force them to junk since the fetch/validate pipeline
    # can't do anything with a video URL anyway.
    "foodnetwork_videos_junk": (
        "SELECT id, url FROM pages WHERE site='foodnetwork' AND url LIKE '%/videos/%'",
        "likely_junk",
    ),
    # Imbibe drink-of-the-week-* — weekly single-subject features. Confirmed by
    # spot-checking fetched HTML: every DOTW page is a product spotlight
    # (single bottle of beer/wine/spirit, tasting set, or coffee), not a
    # mixed-drink recipe with a method. Force the entire slug family to
    # drink_article so the classifier stops splitting them.
    "imbibe_dotw_drink_article": (
        "SELECT id, url FROM pages WHERE site='imbibe' AND url LIKE '%/drink-of-the-week-%'",
        "likely_drink_article",
    ),
    # Foodnetwork /recipes/articles/ — editorial/how-to/roundup section. Every
    # fetched page (incl. recipe-sounding slugs like `easy-cauliflower-pizza-
    # crust-recipe` and `how-to-make-pie-crust`) serves JSON-LD @type=Article,
    # not Recipe. The classifier was splitting this subtree into _article and
    # _recipe labels on slug vibes; force both food and drink entries to the
    # _article label. Food and drink themes are kept separate.
    "foodnetwork_recipes_articles_food_article": (
        "SELECT id, url FROM pages WHERE site='foodnetwork' AND url LIKE '%/recipes/articles/%' AND content_type = 'likely_food_recipe'",
        "likely_food_article",
    ),
    "foodnetwork_recipes_articles_drink_article": (
        "SELECT id, url FROM pages WHERE site='foodnetwork' AND url LIKE '%/recipes/articles/%' AND content_type = 'likely_drink_recipe'",
        "likely_drink_article",
    ),
    # Bonappetit /story/ drink recipes — these pages DO contain real drink
    # recipes in article body but ship NewsArticle schema rather than Recipe,
    # so extruct/JSON-LD validation can't extract them. Mark with a dedicated
    # label so the default fetch pipeline (which targets likely_drink_recipe)
    # skips them, without losing the signal that the URL is a recipe page —
    # a future unstructured extractor can target this label directly.
    "bonappetit_story_unstructured_drink_recipe": (
        "SELECT id, url FROM pages WHERE site='bonappetit' AND url LIKE '%/story/%' AND content_type = 'likely_drink_recipe'",
        "likely_unstructured_drink_recipe",
    ),
}


def run_one(db: Database, key: str, sql: str, label: str, dry_run: bool) -> int:
    """Apply one entry. Returns the number of rows reclassified (or that would
    be reclassified in dry-run)."""
    wrapped = f"""
        SELECT sub.id, sub.url
        FROM ({sql}) AS sub
        JOIN pages p ON p.id = sub.id
        WHERE p.content_type IS NULL OR p.content_type != ?
    """
    rows = db.conn.execute(wrapped, (label,)).fetchall()
    suffix = " (dry run)" if dry_run else ""
    print(f"[{key}] {len(rows)} rows → {label}{suffix}")
    if dry_run or not rows:
        return len(rows)
    raw = json.dumps({"label": label, "key": key})
    for row in rows:
        page = db.conn.execute(
            "SELECT content_type FROM pages WHERE id = ?", (row["id"],),
        ).fetchone()
        db.record_classify_url(
            page_id=row["id"],
            run_id=None,
            label=label,
            model="manual",
            prompt_version="manual",
            raw_response=raw,
            latency_ms=None,
            pages_content_type_before=page["content_type"],
        )
    return len(rows)


def null_one(db: Database, key: str, sql: str, dry_run: bool) -> int:
    """NULL `content_type` for every row matched by the entry's SQL that currently
    has a non-NULL content_type. Use this to force the main classifier to
    reconsider a batch. No audit row is written — the NULL state is itself the
    signal that the page is pending classification."""
    wrapped = f"""
        SELECT sub.id
        FROM ({sql}) AS sub
        JOIN pages p ON p.id = sub.id
        WHERE p.content_type IS NOT NULL
    """
    ids = [r["id"] for r in db.conn.execute(wrapped).fetchall()]
    suffix = " (dry run)" if dry_run else ""
    print(f"[{key}] {len(ids)} rows → NULL{suffix}")
    if dry_run or not ids:
        return len(ids)
    placeholders = ",".join("?" for _ in ids)
    with db._lock:
        db.conn.execute(
            f"UPDATE pages SET content_type = NULL WHERE id IN ({placeholders})",
            ids,
        )
        db.conn.commit()
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="manual_reclassification")
    p.add_argument("keys", nargs="*", help="Keys to run. Omit to run all entries.")
    p.add_argument("--list", action="store_true", help="List all entries and exit.")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would change; do not write.")
    p.add_argument("--null", action="store_true",
                   help="NULL content_type for matched rows instead of setting the "
                        "entry's label. Use to send matches back through the main classifier.")
    args = p.parse_args(argv)

    if args.list:
        for key, (_, label) in RECLASSIFICATIONS.items():
            print(f"{key:<55} → {label}")
        return 0

    keys = args.keys or list(RECLASSIFICATIONS.keys())
    unknown = [k for k in keys if k not in RECLASSIFICATIONS]
    if unknown:
        print(f"Unknown keys: {', '.join(unknown)}", file=sys.stderr)
        print(f"Available: {', '.join(RECLASSIFICATIONS.keys())}", file=sys.stderr)
        return 2

    db = Database(str(DB_PATH))
    try:
        total = 0
        for key in keys:
            sql, label = RECLASSIFICATIONS[key]
            if args.null:
                total += null_one(db, key, sql, args.dry_run)
            else:
                total += run_one(db, key, sql, label, args.dry_run)
        note = " (dry run, nothing written)" if args.dry_run else ""
        print(f"Total: {total}{note}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
