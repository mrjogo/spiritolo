import argparse
import logging
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from scraper.src.cli_common import confirm_reset
from scraper.src.db import Database
from scraper.src.progress import make_progress
from scraper.src.structured import find_recipe
from scraper.src.summary import print_summary
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
) -> dict[str, Counter]:
    """Process the extractor work queue. Returns per-site Counter keyed by
    category ('extracted' / 'no_recipe' / 'missing') — same shape as the
    validate CLI, so scraper.src.summary.print_summary renders both
    uniformly."""
    rows = db.get_unextracted(site=site, limit=limit)
    total = len(rows)
    if total == 0:
        log.info("nothing to extract")
        return {}

    log.info("extracting %d pages", total)
    changes: dict[str, Counter] = {}
    progress = make_progress(total=total)

    def bump(site_name: str, category: str) -> None:
        changes.setdefault(site_name, Counter())[category] += 1

    for idx, row in enumerate(rows, start=1):
        html_path = html_dir / row["html_path"]
        try:
            html = html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            db.mark_extract_error(row["url"], "html_file_missing")
            bump(row["site"], "missing")
            progress(idx)
            continue

        recipe = find_recipe(html)
        if recipe is None:
            db.mark_extract_error(row["url"], "no_recipe")
            bump(row["site"], "no_recipe")
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
            bump(row["site"], "extracted")

        progress(idx)

    return changes


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Extract JSON-LD recipes to Supabase.")
    parser.add_argument("--site", default=None, help="Only process a specific site.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N rows.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--html-dir", default=str(DEFAULT_HTML_DIR))
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear extracted_at and extract_error on drink-recipe rows before "
             "extracting (scoped by --site if given).",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the --reset confirmation prompt. Required when stdin is "
             "not a terminal.",
    )
    args = parser.parse_args()

    db = Database(args.db)
    sb = SupabaseClient()
    try:
        if args.reset:
            # Count what the reset would affect so confirm_reset can show it.
            rows = db.get_unextracted(site=args.site)
            # Actually we want "how many rows CURRENTLY have extracted_at or
            # extract_error set and would be cleared". Query directly.
            placeholders = ",".join("?" for _ in db.EXTRACT_CONTENT_TYPES)
            q = (
                f"SELECT COUNT(*) c FROM pages WHERE content_type IN ({placeholders}) "
                "AND (extracted_at IS NOT NULL OR extract_error IS NOT NULL)"
            )
            params: list = list(db.EXTRACT_CONTENT_TYPES)
            if args.site:
                q += " AND site = ?"
                params.append(args.site)
            already = db.conn.execute(q, params).fetchone()["c"]
            scope = f"site={args.site}" if args.site else "all sites"
            if not confirm_reset(
                row_count=already, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if already:
                n = db.reset_extract_state(site=args.site)
                log.info("reset extract state on %d rows", n)

        changes = extract_pages(
            db=db,
            sb=sb,
            html_dir=Path(args.html_dir),
            site=args.site,
            limit=args.limit,
        )
        print_summary("Extract", changes)
        return 0
    finally:
        db.close()
        sb.close()


if __name__ == "__main__":
    main()
