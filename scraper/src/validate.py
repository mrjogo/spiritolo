"""Validate CLI: re-run validate() + classify_drink() on cached HTML.

Work queue is "pages with html_path set that have no validate_html_runs row"
so runs are resumable (restart picks up where it left off) and arbitrary
subsets can be re-processed by clearing the relevant rows via SQL or --reset.

Each invocation:
  1. Opens a pipeline_runs row with stage='validate_html'.
  2. For each page in the queue, writes one validate_html_runs row and one
     classify_drink_runs row (UPSERT on page_id — latest-only). Each row
     carries the run_id, evaluator version, and a snapshot of the pages.*
     field the stage mutates, captured RIGHT BEFORE this evaluation ran.
  3. Writes new pages.status / pages.content_type for the denormalized cache.
  4. Closes the pipeline_runs row with the summary Counter we already print.

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

from spiritolo_common.cli_common import (
    add_reset_args, confirm_reset, describe_reset_scope,
)
from scraper.src.classify_drink import SCORER_VERSION, classify_drink_scored
from scraper.src.db import Database
from spiritolo_common.progress import make_progress
from spiritolo_common.summary import print_summary
from scraper.src.validation import VALIDATOR_VERSION, validate

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
    spiritolo_common.summary.print_summary.
    """
    rows = db.get_pending_validate_html(site=site, limit=limit)
    total = len(rows)
    if total == 0:
        log.info("no pending rows — nothing to validate")
        return {}

    scope = f" (site={site})" if site else ""
    log.info("validating %d pages%s", total, scope)

    run_id: int | None = None
    if not dry_run:
        run_id = db.start_run(
            stage="validate_html",
            site=site,
            args={"limit": limit, "dry_run": dry_run},
        )

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

        page_id = row["id"]
        old_status = row["status"]
        old_ct = row["content_type"]

        # --- validate flow (status) ---
        result = validate(html, url=row["url"])
        new_status = result.status
        if new_status != old_status:
            changes.setdefault(row["site"], Counter())[
                f"{old_status} -> {new_status}"
            ] += 1
            if not dry_run:
                if new_status == "blocked":
                    db.mark_blocked(row["url"])
                else:
                    db.mark_content(row["url"], new_status, html_path=row["html_path"])

        if not dry_run:
            db.record_validate_html(
                page_id=page_id,
                run_id=run_id,
                status=new_status,
                reason=result.reason,
                validator_version=VALIDATOR_VERSION,
                pages_status_before=old_status,
            )

        # --- classify_drink flow (content_type) ---
        # Run the scored classifier even on 'blocked' pages so we always have
        # provenance; the score will be 0 (no recipe) and the label None.
        classification = classify_drink_scored(html)
        if new_status != "blocked":
            if classification.label is not None and classification.label != old_ct:
                changes.setdefault(row["site"], Counter())[
                    f"{old_ct or 'NULL'} -> {classification.label}"
                ] += 1
                if not dry_run:
                    db.set_content_type(row["url"], classification.label)

        if not dry_run:
            db.record_classify_drink(
                page_id=page_id,
                run_id=run_id,
                label=classification.label,
                score=classification.score,
                score_detail={"rules": classification.rules},
                scorer_version=SCORER_VERSION,
                pages_content_type_before=old_ct,
            )

        progress(idx)

    if not dry_run and run_id is not None:
        summary_dict = {site_key: dict(counter) for site_key, counter in changes.items()}
        db.finish_run(run_id, summary={"transitions": summary_dict, "missing": missing})

    if missing:
        log.warning("%d rows had html_path set but file was missing", missing)
    return changes


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate",
        description=(
            "Re-run validate + classify_drink on cached HTML. Work queue is "
            "pages with cached HTML that have no validate_html_runs row — "
            "runs are resumable; kill it any time and re-invoke to pick up "
            "where it left off."
        ),
    )
    parser.add_argument("--site", help="Only process a specific site.")
    parser.add_argument("--limit", type=int, help="Process at most N rows.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report transitions without writing to the DB or recording eval rows.",
    )
    add_reset_args(parser, stage="validate_html_runs + classify_drink_runs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    db = Database(DEFAULT_DB_PATH)
    try:
        if args.reset:
            # Validate's --reset clears BOTH eval tables together: they're
            # written together and the work queue picks up a page if either
            # is missing, so leaving one half behind would leak audit rows
            # without changing scheduling. --except-version applies to each
            # table's own version column (validator_version on one,
            # scorer_version on the other), so bumping either constant and
            # passing --except-version V re-queues the same set of pages.
            v_count = db.count_eval_rows(
                "validate_html_runs",
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            d_count = db.count_eval_rows(
                "classify_drink_runs",
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            scope = describe_reset_scope(
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            if not confirm_reset(
                row_count=v_count + d_count,
                scope_desc=scope,
                assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if v_count + d_count:
                v = db.clear_eval_rows(
                    "validate_html_runs",
                    site=args.site,
                    except_version=args.except_version,
                    older_than=args.older_than,
                )
                d = db.clear_eval_rows(
                    "classify_drink_runs",
                    site=args.site,
                    except_version=args.except_version,
                    older_than=args.older_than,
                )
                log.info("cleared %d validate_html_runs + %d classify_drink_runs rows", v, d)

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
