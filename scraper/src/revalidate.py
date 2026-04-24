import argparse
import logging
import time
from collections import Counter
from pathlib import Path

from scraper.src.db import Database
from scraper.src.validate import classify_drink, validate

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

log = logging.getLogger("revalidate")

PROGRESS_EVERY = 250


def revalidate(
    db: Database,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    dry_run: bool = False,
) -> dict[str, Counter]:
    """Re-run validate() + classify_drink() on every cached HTML.

    The validate (status) and classify_drink (content_type) flows are
    independent: a row whose validate status stays at "Recipe" can still have
    its content_type flipped when the scored classifier disagrees with the
    old label — which is the whole point of running revalidate after a
    classifier change.

    Abstain (classify_drink returns None) preserves the existing content_type
    rather than clearing it, so an earlier LLM- or human-assigned label is
    never erased by a rule set that isn't confident enough to overrule it.
    """
    query = (
        "SELECT url, site, status, content_type, html_path "
        "FROM pages WHERE html_path IS NOT NULL"
    )
    params: list = []
    if site:
        query += " AND site = ?"
        params.append(site)
    query += " ORDER BY site, id"

    with db._lock:
        rows = db.conn.execute(query, params).fetchall()

    total = len(rows)
    if total == 0:
        log.info("no cached HTML to revalidate")
        return {}

    log.info("revalidating %d pages%s", total, f" (site={site})" if site else "")
    changes: dict[str, Counter] = {}
    missing = 0
    started = time.monotonic()

    for idx, row in enumerate(rows, start=1):
        html_file = html_dir / row["html_path"]
        if not html_file.exists():
            missing += 1
            continue
        html = html_file.read_text(encoding="utf-8")

        # --- status flow (validate) ---
        result = validate(html, url=row["url"])
        old_status = row["status"]
        new_status = result.status
        if new_status != old_status:
            changes.setdefault(row["site"], Counter())[f"{old_status} -> {new_status}"] += 1
            if not dry_run:
                if new_status == "blocked":
                    db.mark_blocked(row["url"], result.reason or "blocked")
                else:
                    db.mark_content(
                        row["url"],
                        new_status,
                        result.reason or new_status,
                        html_path=row["html_path"],
                    )

        # --- content_type flow (classify_drink) ---
        # Only meaningful on Recipe-status pages; validate.status doubling as
        # a gate is fine because classify_drink abstains on non-Recipe HTML.
        if new_status != "blocked":
            predicted = classify_drink(html)
            old_ct = row["content_type"]
            if predicted is not None and predicted != old_ct:
                changes.setdefault(row["site"], Counter())[
                    f"{old_ct or 'NULL'} -> {predicted}"
                ] += 1
                if not dry_run:
                    db.set_content_type(row["url"], predicted)

        if idx % PROGRESS_EVERY == 0 or idx == total:
            elapsed = time.monotonic() - started
            rate = idx / elapsed if elapsed > 0 else 0.0
            remaining = total - idx
            eta = remaining / rate if rate > 0 else 0.0
            log.info(
                "progress %d/%d (%.1f rows/sec, ETA %.0fs)",
                idx, total, rate, eta,
            )

    if missing:
        log.warning("%d rows had html_path set but file was missing", missing)
    return changes


def _print_summary(changes: dict[str, Counter], dry_run: bool) -> None:
    print("\n--- Revalidation ---")
    if not changes:
        print("No changes.")
        return
    total = 0
    for site_name in sorted(changes):
        print(f"  {site_name}:")
        for transition, count in changes[site_name].most_common():
            print(f"    {count:6d}  {transition}")
            total += count
    mode = "dry-run" if dry_run else "applied"
    print(f"Total: {total} ({mode})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Re-run validate() + classify_drink() on cached HTML and update status / content_type"
    )
    parser.add_argument("--site", help="Only revalidate a specific site")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    db = Database(DEFAULT_DB_PATH)
    changes = revalidate(db, site=args.site, dry_run=args.dry_run)
    _print_summary(changes, args.dry_run)
    db.close()
