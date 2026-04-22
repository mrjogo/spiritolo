import argparse
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from scraper.src.db import Database
from scraper.src.jsonld import derive_author, derive_image_url, parse_recipe_from_html
from scraper.src.supabase_client import SupabaseClient

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

log = logging.getLogger("extract")


def extract_pages(
    *,
    db: Database,
    sb: SupabaseClient,
    html_dir: Path,
    site: str | None = None,
    limit: int | None = None,
) -> dict:
    """Process the extractor work queue. Returns {'extracted': N, 'no_jsonld': M, 'missing': K}."""
    rows = db.get_unextracted(site=site, limit=limit)
    total = len(rows)
    if total == 0:
        log.info("nothing to extract")
        return {"extracted": 0, "no_jsonld": 0, "missing": 0}

    log.info("extracting %d pages", total)
    extracted = 0
    no_jsonld = 0
    missing = 0
    started = time.monotonic()

    for idx, row in enumerate(rows, start=1):
        html_path = html_dir / row["html_path"]
        try:
            html = html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            db.mark_extract_error(row["url"], "html_file_missing")
            missing += 1
            continue

        recipe = parse_recipe_from_html(html)
        if recipe is None:
            db.mark_extract_error(row["url"], "no_jsonld_recipe")
            no_jsonld += 1
        else:
            sb.upsert_recipe(
                source_url=row["url"],
                site=row["site"],
                name=recipe.get("name") if isinstance(recipe.get("name"), str) else None,
                author=derive_author(recipe),
                image_url=derive_image_url(recipe),
                jsonld=recipe,
                fetched_at=row["fetched_at"],
            )
            db.mark_extracted(row["url"])
            extracted += 1

        if idx % 25 == 0 or idx == total:
            elapsed = time.monotonic() - started
            rate = idx / elapsed if elapsed > 0 else 0.0
            remaining = total - idx
            eta = remaining / rate if rate > 0 else 0.0
            log.info("progress %d/%d (%.1f rows/sec, ETA %.0fs)", idx, total, rate, eta)

    return {"extracted": extracted, "no_jsonld": no_jsonld, "missing": missing}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Extract JSON-LD recipes to Supabase.")
    parser.add_argument("--site", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--html-dir", default=str(DEFAULT_HTML_DIR))
    args = parser.parse_args()

    db = Database(args.db)
    sb = SupabaseClient()
    try:
        stats = extract_pages(
            db=db,
            sb=sb,
            html_dir=Path(args.html_dir),
            site=args.site,
            limit=args.limit,
        )
        log.info("done: %s", stats)
    finally:
        db.close()
        sb.close()


if __name__ == "__main__":
    main()
