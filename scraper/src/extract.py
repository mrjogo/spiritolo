import argparse
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from scraper.src.db import Database
from scraper.src.structured import find_recipe
from scraper.src.supabase_client import SupabaseClient

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

log = logging.getLogger("extract")


def derive_name(recipe: dict) -> str | None:
    name = recipe.get("name")
    if isinstance(name, str):
        return name or None
    if isinstance(name, list):
        for n in name:
            if isinstance(n, str) and n:
                return n
    return None


def derive_author(recipe: dict) -> str | None:
    author = recipe.get("author")
    if isinstance(author, str):
        return author or None
    if isinstance(author, dict):
        name = author.get("name")
        return name if isinstance(name, str) and name else None
    if isinstance(author, list):
        for a in author:
            derived = derive_author({"author": a})
            if derived:
                return derived
    return None


def derive_image_url(recipe: dict) -> str | None:
    image = recipe.get("image")
    if isinstance(image, str):
        return image or None
    if isinstance(image, dict):
        url = image.get("url")
        return url if isinstance(url, str) and url else None
    if isinstance(image, list) and image:
        for item in image:
            derived = derive_image_url({"image": item})
            if derived:
                return derived
    return None


def extract_pages(
    *,
    db: Database,
    sb: SupabaseClient,
    html_dir: Path,
    site: str | None = None,
    limit: int | None = None,
) -> dict:
    """Process the extractor work queue. Returns {'extracted': N, 'no_recipe': M, 'missing': K}."""
    rows = db.get_unextracted(site=site, limit=limit)
    total = len(rows)
    if total == 0:
        log.info("nothing to extract")
        return {"extracted": 0, "no_recipe": 0, "missing": 0}

    log.info("extracting %d pages", total)
    extracted = 0
    no_recipe = 0
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

        recipe = find_recipe(html)
        if recipe is None:
            db.mark_extract_error(row["url"], "no_recipe")
            no_recipe += 1
        else:
            sb.upsert_recipe(
                source_url=row["url"],
                site=row["site"],
                name=derive_name(recipe),
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

    return {"extracted": extracted, "no_recipe": no_recipe, "missing": missing}


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
