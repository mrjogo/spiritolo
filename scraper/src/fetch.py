import argparse
import hashlib
import time
from pathlib import Path

from scraper.src.client import ScraperAPIClient
from scraper.src.db import Database
from scraper.src.validate import validate, classify_drink

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

CIRCUIT_BREAKER_WINDOW = 20
CIRCUIT_BREAKER_THRESHOLD = 0.4  # 40% failure rate


def url_to_filename(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16] + ".html"


def save_html(html_dir: Path, site_name: str, filename: str, html: str) -> str:
    site_dir = html_dir / site_name
    site_dir.mkdir(parents=True, exist_ok=True)
    file_path = site_dir / filename
    file_path.write_text(html, encoding="utf-8")
    return f"{site_name}/{filename}"


def check_circuit_breaker(recent_statuses: list[str]) -> bool:
    n = len(recent_statuses)
    if n < CIRCUIT_BREAKER_WINDOW:
        return False
    window = recent_statuses[:CIRCUIT_BREAKER_WINDOW]
    bad_count = sum(1 for s in window if s == "blocked")
    return bad_count / CIRCUIT_BREAKER_WINDOW > CIRCUIT_BREAKER_THRESHOLD


def fetch_pages(
    db: Database,
    client: ScraperAPIClient,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    limit: int | None = None,
    force_site: str | None = None,
    content_type: str | None = "likely_drink_recipe",
    delay: float = 1.5,
) -> dict:
    pending = db.get_pending(site=site or force_site, limit=limit, content_type=content_type)
    paused_sites: set[str] = set()
    results: dict = {"blocked": 0, "errors": 0, "paused_sites": []}

    total = len(pending)
    for i, row in enumerate(pending):
        page_site = row["site"]
        url = row["url"]

        # Circuit breaker check (skip if --force-site)
        if page_site not in paused_sites and page_site != force_site:
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                print(f"[{page_site}] PAUSED — >{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% of last {CIRCUIT_BREAKER_WINDOW} pages failed validation")
                paused_sites.add(page_site)

        if page_site in paused_sites:
            continue

        print(f"[{page_site}] {i+1}/{total} — {url}")

        try:
            html = client.fetch(url)
        except Exception as e:
            db.mark_failed(url, str(e))
            results["errors"] += 1
            print(f"  ERROR: {e}")
            if delay > 0:
                time.sleep(delay)
            continue

        result = validate(html)

        if result.status == "blocked":
            db.mark_blocked(url, result.reason or "blocked")
            results["blocked"] += 1
            print(f"  BLOCKED: {result.reason}")
        else:
            filename = url_to_filename(url)
            rel_path = save_html(html_dir, page_site, filename, html)
            db.mark_content(url, result.status, result.reason or result.status, html_path=rel_path)
            results[result.status] = results.get(result.status, 0) + 1
            print(f"  {result.status}: {result.reason}")

            # Classify drink/food from JSON-LD
            drink_result = classify_drink(html)
            if drink_result:
                db.set_content_type(url, drink_result)

        # Re-check circuit breaker after each fetch to detect mid-run failures
        if page_site not in paused_sites and page_site != force_site:
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                print(f"[{page_site}] PAUSED — >{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% of last {CIRCUIT_BREAKER_WINDOW} pages failed validation")
                paused_sites.add(page_site)

        if delay > 0:
            time.sleep(delay)

    results["paused_sites"] = list(paused_sites)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch pending recipe pages via ScraperAPI")
    parser.add_argument("--site", help="Only fetch for a specific site")
    parser.add_argument("--limit", type=int, help="Max number of pages to fetch")
    parser.add_argument("--force-site", help="Resume a paused site (bypasses circuit breaker)")
    parser.add_argument(
        "--content-type",
        default="likely_drink_recipe",
        help="Filter pending pages by content_type (default: likely_drink_recipe). Pass 'any' to disable the filter.",
    )
    args = parser.parse_args()
    content_type = None if args.content_type == "any" else args.content_type

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(DEFAULT_DB_PATH)
    client = ScraperAPIClient()

    results = fetch_pages(
        db,
        client,
        site=args.site,
        limit=args.limit,
        force_site=args.force_site,
        content_type=content_type,
    )

    print("\n--- Results ---")
    print(f"Blocked:    {results['blocked']}")
    print(f"Errors:     {results['errors']}")
    other = {k: v for k, v in results.items() if k not in ("blocked", "errors", "paused_sites") and v}
    for status, count in sorted(other.items()):
        print(f"{status + ':':12s}{count}")
    if results["paused_sites"]:
        print(f"Paused:     {', '.join(results['paused_sites'])}")

    stats = db.get_stats()
    print("\n--- Overall ---")
    for site_name, counts in stats.items():
        parts = [f"{status}: {count}" for status, count in counts.items()]
        print(f"  {site_name}: {', '.join(parts)}")

    db.close()
