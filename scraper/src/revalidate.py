import argparse
from collections import Counter
from pathlib import Path

from scraper.src.db import Database
from scraper.src.validate import classify_drink, validate

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"


def revalidate(
    db: Database,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    dry_run: bool = False,
) -> dict[str, Counter]:
    """Re-run validate() on every cached HTML and update status if it changed."""
    query = "SELECT url, site, status, html_path FROM pages WHERE html_path IS NOT NULL"
    params: list = []
    if site:
        query += " AND site = ?"
        params.append(site)
    query += " ORDER BY site, id"

    with db._lock:
        rows = db.conn.execute(query, params).fetchall()

    changes: dict[str, Counter] = {}
    missing = 0
    for row in rows:
        html_file = html_dir / row["html_path"]
        if not html_file.exists():
            missing += 1
            continue
        html = html_file.read_text(encoding="utf-8")
        result = validate(html, url=row["url"])
        old = row["status"]
        new = result.status
        if new == old:
            continue

        changes.setdefault(row["site"], Counter())[f"{old} -> {new}"] += 1
        if dry_run:
            continue

        if new == "blocked":
            db.mark_blocked(row["url"], result.reason or "blocked")
        else:
            db.mark_content(
                row["url"],
                new,
                result.reason or new,
                html_path=row["html_path"],
            )
            drink_result = classify_drink(html)
            if drink_result:
                db.set_content_type(row["url"], drink_result)

    if missing:
        print(f"warning: {missing} rows had html_path set but file was missing")
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run validate() on cached HTML and update status")
    parser.add_argument("--site", help="Only revalidate a specific site")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    db = Database(DEFAULT_DB_PATH)
    changes = revalidate(db, site=args.site, dry_run=args.dry_run)

    print("\n--- Revalidation ---")
    if not changes:
        print("No status changes.")
    else:
        total = 0
        for site_name in sorted(changes):
            print(f"  {site_name}:")
            for transition, count in changes[site_name].most_common():
                print(f"    {count:6d}  {transition}")
                total += count
        mode = "dry-run" if args.dry_run else "applied"
        print(f"Total: {total} ({mode})")

    db.close()
