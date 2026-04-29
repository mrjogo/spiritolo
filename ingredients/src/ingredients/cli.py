"""parse_ingredients CLI.

Subcommands:
  parse   (default) Polling worker. Reads `recipes` from Supabase, parses each
          row's recipeIngredient array, writes rows to recipe_ingredients.
          Skips recipes that already have rows at the current PARSER_VERSION.
          Bare flags (--review, --site, --limit, --dry-run, --reset …) also
          accepted at the top level for backward compatibility.
  map     Taxonomy mapper. Phase 1 (alias + lexical) by default.

Reset flow (matches scraper conventions):
  --reset --yes [--site S] [--except-version V] [--older-than ISO_TS]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter

from spiritolo_common.cli_common import (
    add_reset_args, confirm_reset, describe_reset_scope,
)
from spiritolo_common.progress import make_progress
from spiritolo_common.summary import print_summary

from ingredients.db import IngredientsDatabase
from ingredients.eval_set import run_eval
from ingredients.parser import PARSER_VERSION
from ingredients.worker import build_rows_for_recipe

log = logging.getLogger("parse_ingredients")


def _add_parse_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--review", action="store_true",
        help="Run the eval set against the parser; do not touch the database.",
    )
    p.add_argument(
        "--site", default=None,
        help="Restrict processing to one source site (e.g. 'punch').",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N recipes.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Parse and report counts; do not write to the database.",
    )
    add_reset_args(p, stage="recipe_ingredients")


def _add_map_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--review", action="store_true",
        help="Run the mapper eval set; do not touch the database.",
    )
    p.add_argument(
        "--site", default=None,
        help="Restrict to one source site.",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N distinct names.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Compute resolutions; do not write to the database.",
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Spot-check N random pending names; print results, write nothing.",
    )
    add_reset_args(p, stage="recipe_ingredients (mapping columns)")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse_ingredients",
        description="Spiritolo ingredient parser + taxonomy mapper.",
    )
    # Top-level parse args for backward compatibility: callers that do
    # build_arg_parser().parse_args(["--review"]) without a subcommand
    # still get a valid namespace (args.cmd will be None).
    _add_parse_args(parser)

    sub = parser.add_subparsers(dest="cmd")

    # Parse subcommand (default — preserves backward-compatible CLI).
    p_parse = sub.add_parser("parse", help="Parser worker (default).")
    _add_parse_args(p_parse)

    # Map subcommand: Phase 1 (alias + lexical).
    p_map = sub.add_parser("map", help="Taxonomy mapper. Phase 1 by default.")
    _add_map_args(p_map)
    map_sub = p_map.add_subparsers(dest="map_cmd")
    # Phase 2 + review subcommands attach to map_sub in Tasks 18/19.
    p_resolve = map_sub.add_parser(
        "resolve-pending",
        help="Phase 2 — drain the pending_llm queue using the chosen provider.",
    )
    p_resolve.add_argument(
        "--provider", choices=["claude", "ollama"], required=True,
        help="LLM provider to use.",
    )
    p_resolve.add_argument("--limit", type=int, default=None,
                           help="Process at most N distinct pending names.")
    p_resolve.add_argument("--yes", action="store_true",
                           help="Skip the residual-count confirmation prompt.")

    p_review = map_sub.add_parser(
        "review-proposals",
        help="Walk the pending taxonomy_proposals queue interactively.",
    )
    p_review.add_argument(
        "--decided-by", default=os.environ.get("USER", "operator"),
        help="Name recorded on each decision.",
    )

    return parser


def run_review() -> int:
    result = run_eval()
    print(f"--- Parser eval ---")
    print(f"  passed: {result['passed']}")
    print(f"  failed: {result['failed']}")
    if result["failed"]:
        print()
        print("Failures:")
        for case in result["cases"]:
            if case["ok"]:
                continue
            r = case["result"]
            print(
                f"  {case['raw']!r}\n"
                f"    -> status={r.parse_status} rule={r.parser_rule} "
                f"amount={r.amount} amount_max={r.amount_max} "
                f"unit={r.unit} name={r.name!r}"
            )
        return 1
    return 0


def run_worker(args: argparse.Namespace) -> int:
    db = IngredientsDatabase()
    try:
        if args.reset:
            to_delete = db.count_eval_rows(
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
                row_count=to_delete, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if to_delete:
                n = db.clear_eval_rows(
                    site=args.site,
                    except_version=args.except_version,
                    older_than=args.older_than,
                )
                log.info("cleared %d recipe_ingredients rows", n)

        queue = db.fetch_work_queue(
            parser_version=PARSER_VERSION,
            site=args.site,
            limit=args.limit,
        )
        total = len(queue)
        if total == 0:
            log.info("nothing to parse")
            return 0
        log.info("parsing %d recipes (parser_version=%s)", total, PARSER_VERSION)

        progress = make_progress(total=total)
        changes: dict[str, Counter] = {}

        for idx, recipe in enumerate(queue, start=1):
            site = recipe["site"]
            rows = build_rows_for_recipe(recipe["recipe_ingredient"], site=site)
            if not args.dry_run:
                db.write_recipe_parses(
                    recipe_id=recipe["id"], rows=rows,
                    parser_version=PARSER_VERSION,
                )
            counter = changes.setdefault(site, Counter())
            for r in rows:
                counter[r["parse_status"]] += 1
            progress(idx)

        mode = "dry-run" if args.dry_run else "applied"
        print_summary("Parse ingredients", changes, mode=mode)
        return 0
    finally:
        db.close()


def run_resolve_pending(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import fetch_pending_llm_names
    from ingredients.mapping.llm_resolver import run_phase2
    from ingredients.mapping.mapper import MAPPER_VERSION

    db = IngredientsDatabase()
    try:
        pending = fetch_pending_llm_names(db.conn, mapper_version=MAPPER_VERSION)
        if not pending:
            log.info("nothing pending; queue is empty")
            return 0

        # Show residual count + top-N before any external call so the
        # operator can choose to skip / hand-curate / proceed.
        log.info("%d distinct names pending Phase 2", len(pending))
        for n in pending[:20]:
            log.info("  %s", n)
        if len(pending) > 20:
            log.info("  ... and %d more", len(pending) - 20)

        if not args.yes:
            sys.stderr.write(f"Proceed with --provider {args.provider}? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        if args.provider == "claude":
            from ingredients.mapping.llm_provider_claude import ClaudeProvider
            provider = ClaudeProvider.from_env()
        else:
            from ingredients.mapping.llm_provider_ollama import OllamaProvider
            provider = OllamaProvider.from_env()

        summary = run_phase2(db.conn, provider=provider, limit=args.limit)
        changes = {"all": Counter(summary)}
        print_summary(
            f"Map resolve-pending ({args.provider}, {MAPPER_VERSION})",
            changes, mode="applied",
        )
        return 0
    finally:
        db.close()


def run_review_proposals(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import write_resolution
    from ingredients.mapping.mapper import MAPPER_VERSION
    from ingredients.mapping.proposals import (
        fetch_pending_proposals, mark_decided,
    )

    db = IngredientsDatabase()
    try:
        pending = fetch_pending_proposals(db.conn)
        if not pending:
            log.info("no pending proposals")
            return 0

        for p in pending:
            print()
            print(f"proposal #{p['id']}  raw_string={p['raw_string']!r}  proposed_slug={p['proposed_slug']!r}")
            parent_label = "(none)"
            if p["proposed_parent_id"]:
                row = db.conn.execute(
                    "select slug, display_name from taxonomy_nodes where id = %s",
                    (p["proposed_parent_id"],),
                ).fetchone()
                if row:
                    parent_label = f"{row[1]} ({row[0]}, id={p['proposed_parent_id']})"
            print(f"  parent: {parent_label}")
            print("  closest existing candidates:")
            for c in (p["candidates"] or [])[:5]:
                print(f"    {c.get('display_name')}  sim={c.get('similarity'):.2f}  id={c.get('node_id')}")

            answer = input("[a]pprove / [r]eject / [s]kip / [e]dit slug: ").strip().lower()
            slug = p["proposed_slug"]
            if answer == "e":
                slug = input(f"new slug (was {slug!r}): ").strip() or slug
                answer = "a"  # treat edited as approve

            if answer == "a":
                if not p["proposed_parent_id"]:
                    log.error("cannot approve without a parent_id; rejecting instead")
                    mark_decided(db.conn, proposal_id=p["id"], status="rejected", decided_by=args.decided_by)
                    continue
                # Create the new node + edge + alias; resolve the row.
                # Prefer the LLM's proposed display_name; fall back to a slug
                # derivation for rows that predate the proposed_display_name column.
                display_name = (
                    p.get("proposed_display_name") or slug.replace("_", " ").title()
                )
                new_id = db.conn.execute(
                    "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
                    (slug, display_name),
                ).fetchone()[0]
                db.conn.execute(
                    "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
                    (p["proposed_parent_id"], new_id),
                )
                db.conn.execute(
                    "insert into taxonomy_aliases (alias, node_id) values (%s, %s) on conflict do nothing",
                    (p["raw_string"], new_id),
                )
                db.conn.commit()
                write_resolution(
                    db.conn, normalized_name=p["raw_string"],
                    taxonomy_node_id=new_id, source="llm",
                    mapper_version=MAPPER_VERSION,
                )
                mark_decided(db.conn, proposal_id=p["id"], status="approved", decided_by=args.decided_by)
                log.info("approved %s as node id=%s", slug, new_id)
            elif answer == "r":
                mark_decided(db.conn, proposal_id=p["id"], status="rejected", decided_by=args.decided_by)
                log.info("rejected %s", p["proposed_slug"])
            else:
                continue  # skip
        return 0
    finally:
        db.close()


def run_map(args: argparse.Namespace) -> int:
    if getattr(args, "map_cmd", None) == "resolve-pending":
        return run_resolve_pending(args)
    if getattr(args, "map_cmd", None) == "review-proposals":
        return run_review_proposals(args)
    from ingredients.mapping.mapper import MAPPER_VERSION, run_phase1
    if args.review:
        # Eval runs against the fixture taxonomy in eval_fixture.py, so it
        # needs the test DB. Refuse if TEST_DB_URL isn't set.
        test_url = os.environ.get("TEST_DB_URL")
        if not test_url:
            log.error("--review needs TEST_DB_URL set; see CLAUDE.md")
            return 2
        from ingredients.mapping.eval_set import run_eval
        from ingredients.mapping.eval_fixture import seed
        import psycopg as _psycopg
        with _psycopg.connect(test_url) as conn:
            seed(conn)
            out = run_eval(conn)
        print("--- Mapper eval (fixture taxonomy) ---")
        print(f"  passed: {out['passed']}")
        print(f"  failed: {out['failed']}")
        if out["failed"]:
            print()
            for c in out["cases"]:
                if not c["ok"]:
                    print(f"  {c['raw']!r}\n    -> source={c['source']!r} slug={c['slug']!r}")
            return 1
        return 0
    if args.sample is not None:
        from ingredients.mapping.admin import sample_pending
        from ingredients.mapping.alias_layer import resolve_alias
        from ingredients.mapping.lexical_layer import resolve_lexical
        from ingredients.mapping.mapper import MAPPER_VERSION
        from ingredients.mapping.normalize import normalize_name
        from ingredients.mapping.types import Resolved
        db = IngredientsDatabase()
        try:
            for raw in sample_pending(
                db.conn, n=args.sample, mapper_version=MAPPER_VERSION, site=args.site,
            ):
                normalized = normalize_name(raw)
                a = resolve_alias(db.conn, normalized)
                if isinstance(a, Resolved):
                    print(f"  {raw!r:40s} -> alias  node_id={a.taxonomy_node_id}")
                    continue
                l = resolve_lexical(db.conn, normalized)
                if isinstance(l, Resolved):
                    print(f"  {raw!r:40s} -> lexical node_id={l.taxonomy_node_id}")
                else:
                    print(f"  {raw!r:40s} -> would mark pending_llm")
            return 0
        finally:
            db.close()
    db = IngredientsDatabase()
    try:
        if args.reset:
            from ingredients.mapping.admin import (
                clear_mapping_columns, count_mapped_rows,
            )
            to_clear = count_mapped_rows(
                db.conn,
                site=args.site, except_version=args.except_version,
                older_than=args.older_than,
            )
            scope = describe_reset_scope(
                site=args.site, except_version=args.except_version, older_than=args.older_than,
            )
            if not confirm_reset(
                row_count=to_clear, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if to_clear:
                n = clear_mapping_columns(
                    db.conn,
                    site=args.site, except_version=args.except_version,
                    older_than=args.older_than,
                )
                log.info("cleared mapping columns on %d rows", n)
            return 0
        summary = run_phase1(
            db.conn, site=args.site, limit=args.limit, dry_run=args.dry_run,
        )
        mode = "dry-run" if args.dry_run else "applied"
        changes = {"all": Counter(summary)}
        print_summary(f"Map ingredients (Phase 1, {MAPPER_VERSION})", changes, mode=mode)
        return 0
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_arg_parser()
    # Backward compat: if no subcommand is given, default to "parse".
    # Exception: bare --help/-h should show the top-level help (with
    # subcommand list) rather than the parse subcommand help.
    argv = sys.argv[1:]
    if argv and argv[0] not in ("parse", "map", "--help", "-h"):
        argv = ["parse"] + argv
    elif not argv:
        argv = ["parse"] + argv
    args = parser.parse_args(argv)
    cmd = args.cmd or "parse"
    if cmd == "parse":
        if args.review:
            return run_review()
        return run_worker(args)
    if cmd == "map":
        return run_map(args)
    parser.error(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
