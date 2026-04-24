"""Prune CLI: delete rows from eval tables to manage DB disk usage.

Eval tables (`classify_url_runs`, `validate_html_runs`, `classify_drink_runs`,
`extract_runs`) are latest-only and regeneratable — dropping rows just puts
pages back on the corresponding stage's work queue. Canonical state in
`pages` is never touched.

`pipeline_runs` rows are deliberately NOT pruned here: they're the audit
trail for what-ran-when, independent of evaluator output, and they're tiny.

Usage:
    prune --stage validate_html --older-than 2026-01-01T00:00:00+00:00
    prune --stage classify_drink --except-version v2
    prune --stage classify_url --site imbibe
    prune --all   # wipe every eval table, keep pipeline_runs

Filters AND together: --older-than + --except-version + --site deletes only
rows that match every condition. Without filters, --stage empties the whole
table for that stage.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scraper.src.cli_common import confirm_reset
from scraper.src.db import Database

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"

log = logging.getLogger("prune")


# Stage-name → (table, version-column). This is the source of truth for which
# stages the prune CLI knows about; adding a new eval table means adding a
# row here.
STAGE_TABLES: dict[str, tuple[str, str]] = {
    "classify_url":   ("classify_url_runs",   "prompt_version"),
    "validate_html":  ("validate_html_runs",  "validator_version"),
    "classify_drink": ("classify_drink_runs", "scorer_version"),
    "extract":        ("extract_runs",        "extractor_version"),
}


def prune_stage(
    db: Database,
    stage: str,
    *,
    older_than: str | None = None,
    except_version: str | None = None,
    site: str | None = None,
) -> int:
    """Delete rows from one eval table, matching the given filters.

    No filters → delete everything in that stage's table.
    Returns the number of rows deleted."""
    if stage not in STAGE_TABLES:
        raise ValueError(
            f"unknown stage: {stage!r}. known stages: {sorted(STAGE_TABLES)}"
        )
    table, version_col = STAGE_TABLES[stage]

    wheres: list[str] = []
    params: list = []
    if older_than is not None:
        wheres.append("evaluated_at < ?")
        params.append(older_than)
    if except_version is not None:
        wheres.append(f"{version_col} != ?")
        params.append(except_version)
    if site is not None:
        wheres.append("page_id IN (SELECT id FROM pages WHERE site = ?)")
        params.append(site)

    query = f"DELETE FROM {table}"
    if wheres:
        query += " WHERE " + " AND ".join(wheres)

    with db._lock:
        cursor = db.conn.execute(query, params)
        db.conn.commit()
        return cursor.rowcount


def prune_all(db: Database) -> dict[str, int]:
    """Wipe every eval table. Leaves pipeline_runs alone."""
    counts: dict[str, int] = {}
    for _stage, (table, _v) in STAGE_TABLES.items():
        with db._lock:
            cursor = db.conn.execute(f"DELETE FROM {table}")
            db.conn.commit()
            counts[table] = cursor.rowcount
    return counts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="prune",
        description="Prune rows from eval tables (classify_url_runs, "
                    "validate_html_runs, classify_drink_runs, extract_runs). "
                    "Pages are untouched; pruned rows go back on the stage's "
                    "work queue next run. pipeline_runs is never modified.",
    )
    parser.add_argument(
        "--stage", choices=sorted(STAGE_TABLES),
        help="Which eval table to prune. Required unless --all is given.",
    )
    parser.add_argument(
        "--older-than", metavar="ISO_TS",
        help="Delete rows whose evaluated_at is before this ISO-8601 timestamp. "
             "Example: 2026-01-01T00:00:00+00:00",
    )
    parser.add_argument(
        "--except-version", metavar="V",
        help="Delete rows whose evaluator version is NOT this value. "
             "Use to drop all rows from prior prompt/scorer versions.",
    )
    parser.add_argument("--site", help="Scope to a single site (joined via pages).")
    parser.add_argument(
        "--all", action="store_true",
        help="Delete every row from every eval table. Overrides other flags. "
             "pipeline_runs is preserved.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt. Required when stdin is not a terminal.",
    )
    return parser.parse_args(argv)


def _count_matching(db: Database, stage: str, **filters) -> int:
    """Count rows that prune_stage would delete with the same filters."""
    table, version_col = STAGE_TABLES[stage]
    wheres: list[str] = []
    params: list = []
    if filters.get("older_than") is not None:
        wheres.append("evaluated_at < ?")
        params.append(filters["older_than"])
    if filters.get("except_version") is not None:
        wheres.append(f"{version_col} != ?")
        params.append(filters["except_version"])
    if filters.get("site") is not None:
        wheres.append("page_id IN (SELECT id FROM pages WHERE site = ?)")
        params.append(filters["site"])
    query = f"SELECT COUNT(*) c FROM {table}"
    if wheres:
        query += " WHERE " + " AND ".join(wheres)
    with db._lock:
        return db.conn.execute(query, params).fetchone()["c"]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    if not args.all and args.stage is None:
        log.error("must specify --stage <name> or --all")
        return 2

    db = Database(DEFAULT_DB_PATH)
    try:
        if args.all:
            # Count-then-confirm across all tables so the prompt shows the
            # real blast radius before anyone types y.
            total = 0
            for _stage, (table, _v) in STAGE_TABLES.items():
                total += db.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            if not confirm_reset(
                row_count=total, scope_desc="all eval tables",
                assume_yes=args.yes,
            ):
                log.error("prune aborted")
                return 1
            counts = prune_all(db)
            for table, n in counts.items():
                log.info("%s: %d rows deleted", table, n)
            return 0

        to_delete = _count_matching(
            db, args.stage,
            older_than=args.older_than,
            except_version=args.except_version,
            site=args.site,
        )
        filters = []
        if args.older_than:
            filters.append(f"older-than={args.older_than}")
        if args.except_version:
            filters.append(f"except-version={args.except_version}")
        if args.site:
            filters.append(f"site={args.site}")
        scope = f"stage={args.stage}" + ("" if not filters else " (" + ", ".join(filters) + ")")
        if not confirm_reset(
            row_count=to_delete, scope_desc=scope, assume_yes=args.yes,
        ):
            log.error("prune aborted")
            return 1
        deleted = prune_stage(
            db, args.stage,
            older_than=args.older_than,
            except_version=args.except_version,
            site=args.site,
        )
        log.info("%s: %d rows deleted", STAGE_TABLES[args.stage][0], deleted)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
