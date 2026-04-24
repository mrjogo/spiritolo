"""Validate CLI: re-run validate() + classify_drink() on cached HTML.

Work queue is `html_path IS NOT NULL AND validated_at IS NULL`, so runs are
resumable (restart picks up where it left off) and arbitrary subsets can be
re-processed by clearing validated_at via SQL or --reset.

The validate-status flow and the classify_drink content_type flow are
independent: a row whose validate status stays at "Recipe" can still have
its content_type flipped when the scored classifier disagrees with the old
label. Abstain (classify_drink returns None) preserves the existing
content_type rather than clearing it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from scraper.src.cli_common import confirm_reset
from scraper.src.db import Database
from scraper.src.progress import make_progress
from scraper.src.summary import print_summary
from scraper.src.validation import classify_drink, validate

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

log = logging.getLogger("validate")


def revalidate(
    db: Database,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Counter]:
    """Walk the work queue and re-validate each row.

    Returns per-site Counter of transition descriptions, for rendering via
    scraper.src.summary.print_summary.
    """
    query = (
        "SELECT url, site, status, content_type, html_path "
        "FROM pages WHERE html_path IS NOT NULL AND validated_at IS NULL"
    )
    params: list = []
    if site:
        query += " AND site = ?"
        params.append(site)
    query += " ORDER BY site, id"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with db._lock:
        rows = db.conn.execute(query, params).fetchall()

    total = len(rows)
    if total == 0:
        log.info("no pending rows — nothing to validate")
        return {}

    scope = f" (site={site})" if site else ""
    log.info("validating %d pages%s", total, scope)
    changes: dict[str, Counter] = {}
    missing = 0
    progress = make_progress(total=total)

    for idx, row in enumerate(rows, start=1):
        html_file = html_dir / row["html_path"]
        if not html_file.exists():
            missing += 1
            progress(idx)
            continue
        html = html_file.read_text(encoding="utf-8")

        # --- validate flow (status) ---
        result = validate(html, url=row["url"])
        old_status = row["status"]
        new_status = result.status
        if new_status != old_status:
            changes.setdefault(row["site"], Counter())[
                f"{old_status} -> {new_status}"
            ] += 1
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

        # --- classify_drink flow (content_type) ---
        if new_status != "blocked":
            predicted = classify_drink(html)
            old_ct = row["content_type"]
            if predicted is not None and predicted != old_ct:
                changes.setdefault(row["site"], Counter())[
                    f"{old_ct or 'NULL'} -> {predicted}"
                ] += 1
                if not dry_run:
                    db.set_content_type(row["url"], predicted)

        # Stamp validated_at unless this is a dry run. Dry runs must not
        # mutate the work queue — otherwise a preview would silently hide
        # rows from the subsequent real run.
        if not dry_run:
            db.mark_validated(row["url"])

        progress(idx)

    if missing:
        log.warning("%d rows had html_path set but file was missing", missing)
    return changes


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate",
        description=(
            "Re-run validate + classify_drink on cached HTML. Work queue is "
            "`html_path IS NOT NULL AND validated_at IS NULL`, so runs are "
            "resumable — kill it any time and re-invoke to pick up where it "
            "left off."
        ),
    )
    parser.add_argument("--site", help="Only process a specific site.")
    parser.add_argument("--limit", type=int, help="Process at most N rows.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report transitions without writing to the DB or stamping "
             "validated_at.",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear validated_at for in-scope rows before running, forcing "
             "re-processing. Combine with --site for partial re-sweeps; use "
             "raw SQL for anything more exotic.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the --reset confirmation prompt. Required when stdin is "
             "not a terminal (e.g. piped/CI).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    db = Database(DEFAULT_DB_PATH)
    try:
        if args.reset:
            scope = f"site={args.site}" if args.site else "all sites"
            row_count = db.count_pending_validation(site=args.site)
            # count of rows already validated — those are what --reset clears.
            with db._lock:
                q = "SELECT COUNT(*) c FROM pages WHERE html_path IS NOT NULL AND validated_at IS NOT NULL"
                params: list = []
                if args.site:
                    q += " AND site = ?"
                    params.append(args.site)
                already = db.conn.execute(q, params).fetchone()["c"]
            if not confirm_reset(
                row_count=already,
                scope_desc=scope,
                assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if already:
                cleared = db.clear_validated_at(site=args.site)
                log.info("cleared validated_at on %d rows", cleared)

        changes = revalidate(
            db, site=args.site, dry_run=args.dry_run, limit=args.limit,
        )
        print_summary(
            "Validate",
            changes,
            mode="dry-run" if args.dry_run else "applied",
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
