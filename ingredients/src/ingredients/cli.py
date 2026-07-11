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

from common.cli_common import (
    add_reset_args, confirm_reset, describe_reset_scope,
)
from common.interrupt import InterruptHandler
from common.progress import make_progress
from common.summary import print_summary

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


def _add_normalize_names_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--review", action="store_true",
                   help="Run the dedup eval set; do not touch the database.")
    p.add_argument("--site", default=None,
                   help="Restrict to one source site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N distinct names.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute resolutions; do not write to the database.")
    p.add_argument("--sample", type=int, default=None,
                   help="Spot-check N random pending names; print, write nothing.")
    add_reset_args(p, stage="recipes (normalization columns)")


def _add_cluster_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--site", default=None,
                   help="Restrict to one source site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N recipes.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute clusters; do not write to the database.")
    p.add_argument("--review", action="store_true",
                   help="Run the dedup eval set; do not touch the database.")
    add_reset_args(p, stage="recipes (cluster_id, variant_key, dedup_version)")


def _add_recipegf_export_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--review", action="store_true",
                   help="Run the recipegf export eval set; do not touch the database.")
    p.add_argument("--site", default=None,
                   help="Restrict to clusters whose representative recipe is from one site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N clusters.")
    p.add_argument("--dry-run", action="store_true",
                   help="Convert + validate; do not write bundles or proposals to the DB.")
    p.add_argument("--out", default=None, metavar="DIR",
                   help="Also write each emitted bundle as <slug>.json into DIR "
                        "(written even under --dry-run, as a preview artifact).")
    add_reset_args(p, stage="recipe_clusters (recipegf_* columns)")


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
        "--provider", choices=["claude", "ollama", "openai"], required=True,
        help="LLM provider to use.",
    )
    p_resolve.add_argument("--limit", type=int, default=None,
                           help="Process at most N distinct pending names.")
    p_resolve.add_argument("--yes", action="store_true",
                           help="Skip the residual-count confirmation prompt.")
    p_resolve.add_argument(
        "--batch", action="store_true",
        help="Use OpenAI Batch API (50%% off, ~24h SLA). Loops "
             "submit→poll→ingest until the queue (or --limit) is drained. "
             "Only valid with --provider openai.",
    )
    p_resolve.add_argument(
        "--ingest", metavar="BATCH_ID", default=None,
        help="Ingest results from a previously submitted batch and exit. "
             "Implies --batch.",
    )
    p_resolve.add_argument(
        "--force", action="store_true",
        help="With --ingest, re-ingest a sidecar already marked .ingested. "
             "Idempotent against the DB — UPSERTs replay the same writes.",
    )
    p_resolve.add_argument(
        "--chunk-size", type=int, default=2000,
        help="With --batch, names per submitted batch (default: 2000, "
             "sized for the gpt-5-mini 5M enqueued-token tier).",
    )
    p_resolve.add_argument(
        "--poll-interval", type=int, default=600,
        help="With --batch, seconds between status polls (default: 600).",
    )
    p_resolve.add_argument(
        "--model", default=None,
        help="Override the provider's default model id.",
    )

    p_review = map_sub.add_parser(
        "review-proposals",
        help="Walk the pending taxonomy_proposals queue interactively.",
    )
    p_review.add_argument(
        "--decided-by", default=os.environ.get("USER", "operator"),
        help="Name recorded on each decision.",
    )

    p_retry = map_sub.add_parser(
        "retry-failures",
        help="Unpark names parked by the chunked drain "
             "(pending_llm_tried -> pending_llm). Run after the "
             "underlying blocker is resolved (form proposal approved, "
             "taxonomy edit landed, etc.).",
    )
    p_retry.add_argument(
        "--limit", type=int, default=None,
        help="Unpark at most N rows (no ordering guarantees).",
    )
    p_retry.add_argument(
        "--yes", action="store_true",
        help="Skip the count-and-confirm prompt.",
    )

    # normalize-names: Phase 1 by default; resolve-pending / list-pending sub-subcommands.
    p_norm = sub.add_parser("normalize-names",
                            help="Cocktail-name normalization. Phase 1 by default.")
    _add_normalize_names_args(p_norm)
    norm_sub = p_norm.add_subparsers(dest="normalize_cmd")

    p_resolve_norm = norm_sub.add_parser(
        "resolve-pending",
        help="Phase 2 — drain the pending_llm queue using the chosen provider.",
    )
    p_resolve_norm.add_argument("--provider", choices=["claude", "ollama", "openai"], required=True,
                                help="LLM provider to use.")
    p_resolve_norm.add_argument("--limit", type=int, default=None,
                                help="Process at most N distinct pending names.")
    p_resolve_norm.add_argument("--yes", action="store_true",
                                help="Skip the residual-count confirmation prompt.")
    p_resolve_norm.add_argument(
        "--batch", action="store_true",
        help="Use OpenAI Batch API (50%% off, ~24h SLA). Loops "
             "submit→poll→ingest until the queue (or --limit) is drained. "
             "Only valid with --provider openai.",
    )
    p_resolve_norm.add_argument(
        "--ingest", metavar="BATCH_ID", default=None,
        help="Ingest results from a previously submitted batch and exit. "
             "Implies --batch.",
    )
    p_resolve_norm.add_argument(
        "--force", action="store_true",
        help="With --ingest, re-ingest a sidecar already marked .ingested.",
    )
    p_resolve_norm.add_argument(
        "--chunk-size", type=int, default=2000,
        help="With --batch, names per submitted batch (default: 2000, "
             "sized for the gpt-5-mini 5M enqueued-token tier).",
    )
    p_resolve_norm.add_argument(
        "--poll-interval", type=int, default=600,
        help="With --batch, seconds between status polls (default: 600).",
    )
    p_resolve_norm.add_argument(
        "--model", default=None,
        help="Override the provider's default model id.",
    )

    p_list_pending = norm_sub.add_parser(
        "list-pending",
        help="List names queued for Phase 2.",
    )
    p_list_pending.add_argument("--limit", type=int, default=50,
                                help="List at most N names (default: 50).")

    p_retry_norm = norm_sub.add_parser(
        "retry-failures",
        help="Unpark names parked by the chunked drain "
             "(pending_llm_tried -> pending_llm). Run after the "
             "underlying blocker is resolved.",
    )
    p_retry_norm.add_argument(
        "--limit", type=int, default=None,
        help="Unpark at most N rows.",
    )
    p_retry_norm.add_argument(
        "--yes", action="store_true",
        help="Skip the count-and-confirm prompt.",
    )

    # cluster: cluster compute by default; audit sub-subcommand.
    p_cluster = sub.add_parser("cluster",
                               help="Compute clusters + variants from normalized recipes.")
    _add_cluster_args(p_cluster)
    cluster_sub = p_cluster.add_subparsers(dest="cluster_cmd")
    cluster_sub.add_parser("audit",
                           help="Print the five cluster-quality audit signals.")

    # promote-substances.
    p_promote = sub.add_parser("promote-substances",
                               help="Walk the post-D substance-promotion allowlist interactively.")
    p_promote.add_argument("--yes", action="store_true",
                           help="Promote without per-row confirmation.")

    # dedup-all: chained convenience.
    p_all = sub.add_parser("dedup-all",
                           help="Run normalize-names (phase 1) then cluster, in order.")
    _add_cluster_args(p_all)

    # recipegf-export: convert clusters to validated RecipeGF pin-2 bundles.
    p_export = sub.add_parser(
        "recipegf-export",
        help="Emit validated RecipeGF pin-2 bundles from clusters (P2).",
    )
    _add_recipegf_export_args(p_export)
    export_sub = p_export.add_subparsers(dest="recipegf_cmd")
    p_export_review = export_sub.add_parser(
        "review-proposals",
        help="Walk the recipegf_proposals queue interactively.",
    )
    p_export_review.add_argument(
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

        with InterruptHandler() as interrupt:
            for idx, recipe in enumerate(queue, start=1):
                if interrupt.requested:
                    # First Ctrl-C: per-recipe write_recipe_parses commits
                    # atomically, so what's written stays. Stop before the
                    # next recipe.
                    break
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


def run_map_retry_failures(args: argparse.Namespace) -> int:
    """Unpark Phase-2 failures: flip mapper_source 'pending_llm_tried'
    back to 'pending_llm' for the current MAPPER_VERSION."""
    from ingredients.mapping.db import unpark_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    db = IngredientsDatabase()
    try:
        # Show current count first.
        n_parked = db.conn.execute(
            """
            select count(*) from recipe_ingredients
            where mapper_source = 'pending_llm_tried'
              and mapper_version = %s
            """,
            (MAPPER_VERSION,),
        ).fetchone()[0]
        if n_parked == 0:
            log.info("nothing parked at mapper_version=%s", MAPPER_VERSION)
            return 0

        cap = (
            min(args.limit, n_parked) if args.limit is not None else n_parked
        )
        log.info("would unpark %d of %d parked rows at mapper_version=%s",
                 cap, n_parked, MAPPER_VERSION)
        if not args.yes:
            sys.stderr.write("Proceed? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        n = unpark_failures(db.conn, mapper_version=MAPPER_VERSION,
                            limit=args.limit)
        db.conn.commit()
        log.info(
            "unparked %d rows; run 'map resolve-pending --provider …' "
            "to re-submit", n,
        )
        return 0
    finally:
        db.close()


def run_normalize_names_retry_failures(args: argparse.Namespace) -> int:
    """Unpark Phase-2 dedup failures: flip canonical_name_source
    'pending_llm_tried' back to 'pending_llm' for the current
    NORMALIZER_VERSION."""
    from ingredients.dedup.db import unpark_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    db = IngredientsDatabase()
    try:
        n_parked = db.conn.execute(
            """
            select count(*) from recipes
            where canonical_name_source = 'pending_llm_tried'
              and normalizer_version = %s
            """,
            (NORMALIZER_VERSION,),
        ).fetchone()[0]
        if n_parked == 0:
            log.info("nothing parked at normalizer_version=%s", NORMALIZER_VERSION)
            return 0

        cap = (
            min(args.limit, n_parked) if args.limit is not None else n_parked
        )
        log.info("would unpark %d of %d parked rows at normalizer_version=%s",
                 cap, n_parked, NORMALIZER_VERSION)
        if not args.yes:
            sys.stderr.write("Proceed? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        n = unpark_failures(db.conn, normalizer_version=NORMALIZER_VERSION,
                            limit=args.limit)
        db.conn.commit()
        log.info(
            "unparked %d rows; run 'normalize-names resolve-pending --provider …' "
            "to re-submit", n,
        )
        return 0
    finally:
        db.close()


def run_resolve_pending(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import fetch_pending_llm_names
    from ingredients.mapping.llm_resolver import (
        run_phase2, submit_phase2_batch, ingest_phase2_batch,
    )
    from ingredients.mapping.mapper import MAPPER_VERSION
    from pathlib import Path

    BATCHES_DIR = Path("data/batches")

    # Validate flag combos
    if getattr(args, "batch", False) and args.provider != "openai":
        log.error("--batch requires --provider openai")
        return 2
    if getattr(args, "ingest", None) and not getattr(args, "batch", False):
        # --ingest implies --batch
        args.batch = True

    db = IngredientsDatabase()
    try:
        # ---- Batch ingest path (drain a previously-submitted batch) ----
        if getattr(args, "batch", False) and getattr(args, "ingest", None):
            from common.llm.openai_batch import OpenAIBatchProvider
            from common.llm.sidecar import (
                SidecarMismatch, find_ingestable_batch_ids,
                force_unmark_ingested,
            )
            _model = getattr(args, "model", None)
            provider = (
                OpenAIBatchProvider.from_env(model_id=_model)
                if _model else OpenAIBatchProvider.from_env()
            )
            force = getattr(args, "force", False)
            return _run_mapping_ingest(
                db, provider, args.ingest, force=force,
                default_dir=BATCHES_DIR,
            )

        # ---- Pre-flight: count pending and confirm ----
        pending = fetch_pending_llm_names(db.conn, mapper_version=MAPPER_VERSION)
        if not pending:
            log.info("nothing pending; queue is empty")
            return 0

        log.info("%d distinct names pending Phase 2", len(pending))
        for n in pending[:20]:
            log.info("  %s", n)
        if len(pending) > 20:
            log.info("  ... and %d more", len(pending) - 20)

        if getattr(args, "batch", False):
            target = (
                f"at most {args.limit} of {len(pending)}"
                if args.limit is not None else f"all {len(pending)}"
            )
            mode = (
                f"OpenAI Batch API (50% off, ~24h SLA per chunk; "
                f"chunk_size={args.chunk_size}, draining {target})"
            )
        else:
            mode = f"--provider {args.provider}"
        if not args.yes:
            sys.stderr.write(f"Proceed with {mode}? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        # ---- Batch path: drain in chunks until queue/limit exhausted ----
        if getattr(args, "batch", False):
            from common.llm.openai_batch import OpenAIBatchProvider
            _model = getattr(args, "model", None)
            provider = (
                OpenAIBatchProvider.from_env(model_id=_model)
                if _model else OpenAIBatchProvider.from_env()
            )
            return _drain_mapping_in_chunks(
                db, provider, BATCHES_DIR,
                chunk_size=args.chunk_size,
                total_limit=args.limit,
                poll_interval=getattr(args, "poll_interval", 600),
            )

        # ---- Sync path (existing) ----
        _model = getattr(args, "model", None)
        if args.provider == "claude":
            from common.llm.claude import ClaudeProvider
            provider = ClaudeProvider.from_env(model_id=_model) if _model else ClaudeProvider.from_env()
        elif args.provider == "openai":
            from common.llm.openai import OpenAIProvider
            provider = OpenAIProvider.from_env(model_id=_model) if _model else OpenAIProvider.from_env()
        else:
            from common.llm.ollama import OllamaProvider
            provider = OllamaProvider.from_env(model_id=_model) if _model else OllamaProvider.from_env()

        summary = run_phase2(db.conn, provider=provider, limit=args.limit)
        changes = {"all": Counter(summary)}
        print_summary(
            f"Map resolve-pending ({args.provider}, {MAPPER_VERSION})",
            changes, mode="applied",
        )
        return 0
    finally:
        db.close()


def _run_mapping_ingest(db, provider, ingest_arg, *, force: bool, default_dir):
    """Ingest one batch (when ingest_arg is a batch_id) or every loadable
    sidecar in a directory (when ingest_arg is a path to a directory).
    With force=True, also re-ingests sidecars marked .ingested. Skips
    terminal-failed sidecars (.failed/.expired/.cancelled) — those have
    no provider-side results to drain."""
    import os
    from pathlib import Path
    from ingredients.mapping.llm_resolver import ingest_phase2_batch
    from common.llm.sidecar import (
        SidecarMismatch, find_ingestable_batch_ids, force_unmark_ingested,
    )

    if os.path.isdir(ingest_arg):
        batches_dir = Path(ingest_arg)
        batch_ids = find_ingestable_batch_ids(
            batches_dir, include_ingested=force,
        )
        if not batch_ids:
            log.info("no sidecars found in %s", batches_dir)
            return 0
        log.info("ingesting %d batches from %s", len(batch_ids), batches_dir)
    else:
        batches_dir = default_dir
        batch_ids = [ingest_arg]

    aggregate: Counter[str] = Counter()
    for bid in batch_ids:
        try:
            if force:
                force_unmark_ingested(bid, batches_dir=batches_dir)
            counts = ingest_phase2_batch(
                conn=db.conn, provider=provider,
                batch_id=bid, batches_dir=batches_dir,
            )
            log.info("  %s: %s", bid, dict(counts))
            for k, v in counts.items():
                aggregate[k] += v
        except (SidecarMismatch, FileNotFoundError) as exc:
            log.warning("skipping %s: %s", bid, exc)
            continue

    label = (
        f"Map resolve-pending ingest ({len(batch_ids)} batches from {ingest_arg})"
        if os.path.isdir(ingest_arg)
        else f"Map resolve-pending ingest ({ingest_arg})"
    )
    print_summary(label, {"all": aggregate}, mode="applied")
    return 0


def _drain_mapping_in_chunks(
    db, provider, batches_dir,
    *, chunk_size: int, total_limit: int | None, poll_interval: int,
):
    """Drain the pending_llm queue chunk by chunk: submit a chunk, poll
    until completed, ingest, repeat. Intended to be run under nohup/tmux
    for true fire-and-forget on large queues.

    `total_limit` caps the number of distinct names drained across all
    chunks (so `--limit 4000 --chunk-size 2000` runs exactly 2 chunks).
    `total_limit=None` drains until the queue is empty.

    Each chunk's per-chunk size is min(chunk_size, total_limit_remaining).
    """
    import time
    from ingredients.mapping.db import fetch_pending_llm_names, park_attempted_names
    from ingredients.mapping.llm_resolver import (
        ingest_phase2_batch, submit_phase2_batch,
    )
    from ingredients.mapping.mapper import MAPPER_VERSION
    from common.interrupt import InterruptHandler

    # Sleep when OpenAI's enqueued-token tier rejects a submit. The error
    # is structurally a 429 with message "Enqueued token limit reached…";
    # we look for either the HTTP status or the literal phrase to be robust
    # across SDK versions.
    RATE_LIMIT_BACKOFF = 30 * 60   # 30 minutes — long enough for an
                                    # in-flight batch to free some headroom.

    def _is_enqueue_limit(exc: Exception) -> bool:
        text = str(exc).lower()
        if "enqueued token limit" in text or "enqueued tokens" in text:
            return True
        status = getattr(exc, "status_code", None)
        return status == 429

    chunk_idx = 0
    drained = 0
    aggregate_counts: Counter[str] = Counter()
    with InterruptHandler() as interrupt:
        while True:
            if interrupt.requested:
                log.info("interrupted; %d chunks ingested, leaving any in-flight "
                         "batches submitted (use --ingest <id> to drain later)",
                         chunk_idx)
                break
            if total_limit is not None and drained >= total_limit:
                log.info("--limit %d reached; stopping after %d chunks",
                         total_limit, chunk_idx)
                break

            remaining = fetch_pending_llm_names(
                db.conn, mapper_version=MAPPER_VERSION,
            )
            if not remaining:
                log.info("queue drained; all chunks ingested")
                break

            chunk_idx += 1
            this_chunk = chunk_size
            if total_limit is not None:
                this_chunk = min(chunk_size, total_limit - drained)
            log.info(
                "chunk %d: %d names pending; submitting up to %d",
                chunk_idx, len(remaining), this_chunk,
            )

            # ---- submit (with 429 backoff) ----
            while True:
                if interrupt.requested:
                    break
                try:
                    outcome = submit_phase2_batch(
                        db.conn, provider=provider,
                        batches_dir=batches_dir, limit=this_chunk,
                    )
                    break
                except Exception as exc:
                    if not _is_enqueue_limit(exc):
                        raise
                    log.warning(
                        "enqueue-limit hit on chunk %d; sleeping %d min "
                        "and retrying: %s", chunk_idx, RATE_LIMIT_BACKOFF // 60, exc,
                    )
                    time.sleep(RATE_LIMIT_BACKOFF)
            if interrupt.requested:
                break

            batch_id = outcome.submission.batch_id
            log.info(
                "chunk %d submitted: batch %s (%d requests)",
                chunk_idx, batch_id, outcome.submission.request_count,
            )

            # ---- poll until completed ----
            while True:
                if interrupt.requested:
                    break
                st = provider.status(batch_id)
                log.info("chunk %d status=%s (%d/%d)",
                         chunk_idx, st.state, st.completed, st.total)
                if st.state == "completed":
                    break
                if st.state in ("failed", "expired", "cancelled"):
                    log.error(
                        "chunk %d batch %s ended in state %s — stopping",
                        chunk_idx, batch_id, st.state,
                    )
                    from common.llm.sidecar import mark_failed
                    mark_failed(batches_dir / f"{batch_id}.json", state=st.state)
                    return 1
                time.sleep(poll_interval)
            if interrupt.requested:
                break

            # ---- ingest ----
            counts = ingest_phase2_batch(
                conn=db.conn, provider=provider,
                batch_id=batch_id, batches_dir=batches_dir,
            )
            for k, v in counts.items():
                aggregate_counts[k] += v
            drained += outcome.submission.request_count
            log.info("chunk %d ingested: %s (drained %d total)",
                     chunk_idx, dict(counts), drained)

            # Park names that didn't clear ('propose_form', parse error,
            # provider error, etc.) so they don't reappear in the next
            # chunk or the next run. Operator runs `map retry-failures`
            # to unpark after resolving the underlying blocker.
            stuck = park_attempted_names(
                db.conn, mapper_version=MAPPER_VERSION,
                names=list(outcome.submitted_names),
            )
            db.conn.commit()
            if stuck:
                aggregate_counts["parked"] = aggregate_counts.get("parked", 0) + stuck
                log.info("chunk %d parked %d stuck names as pending_llm_tried",
                         chunk_idx, stuck)

    parked_total = aggregate_counts.get("parked", 0)
    if parked_total:
        log.info(
            "parked %d names as pending_llm_tried "
            "(run 'map retry-failures' to retry)",
            parked_total,
        )
    print_summary(
        f"Map resolve-pending ({chunk_idx} chunks, {drained} drained)",
        {"all": aggregate_counts}, mode="applied",
    )
    return 0


def _run_dedup_ingest(db, provider, ingest_arg, *, force: bool, default_dir):
    """Same shape as `_run_mapping_ingest`, but for dedup. See that
    function for the behavioral spec."""
    import os
    from pathlib import Path
    from ingredients.dedup.normalizer_llm import ingest_normalize_names_batch
    from common.llm.sidecar import (
        SidecarMismatch, find_ingestable_batch_ids, force_unmark_ingested,
    )

    if os.path.isdir(ingest_arg):
        batches_dir = Path(ingest_arg)
        batch_ids = find_ingestable_batch_ids(
            batches_dir, include_ingested=force,
        )
        if not batch_ids:
            log.info("no sidecars found in %s", batches_dir)
            return 0
        log.info("ingesting %d batches from %s", len(batch_ids), batches_dir)
    else:
        batches_dir = default_dir
        batch_ids = [ingest_arg]

    aggregate: Counter[str] = Counter()
    for bid in batch_ids:
        try:
            if force:
                force_unmark_ingested(bid, batches_dir=batches_dir)
            counts = ingest_normalize_names_batch(
                conn=db.conn, provider=provider,
                batch_id=bid, batches_dir=batches_dir,
            )
            log.info("  %s: %s", bid, dict(counts))
            for k, v in counts.items():
                aggregate[k] += v
        except (SidecarMismatch, FileNotFoundError) as exc:
            log.warning("skipping %s: %s", bid, exc)
            continue

    label = (
        f"normalize-names ingest ({len(batch_ids)} batches from {ingest_arg})"
        if os.path.isdir(ingest_arg)
        else f"normalize-names resolve-pending ingest ({ingest_arg})"
    )
    print_summary(label, {"all": aggregate}, mode="applied")
    return 0


def _drain_dedup_in_chunks(
    db, provider, batches_dir,
    *, chunk_size: int, total_limit: int | None, poll_interval: int,
):
    """Drain the pending-canonical-names queue in chunks. Same shape as
    `_drain_mapping_in_chunks`; differs only in which writer functions
    are called and the version constant. See that function for the full
    rationale on chunking, 429 backoff, and Ctrl-C handling."""
    import time
    from ingredients.dedup.db import fetch_pending_canonical_names, park_attempted_names
    from ingredients.dedup.normalizer_llm import (
        ingest_normalize_names_batch, submit_normalize_names_batch,
    )
    from ingredients.dedup.version import NORMALIZER_VERSION
    from common.interrupt import InterruptHandler

    RATE_LIMIT_BACKOFF = 30 * 60

    def _is_enqueue_limit(exc: Exception) -> bool:
        text = str(exc).lower()
        if "enqueued token limit" in text or "enqueued tokens" in text:
            return True
        return getattr(exc, "status_code", None) == 429

    chunk_idx = 0
    drained = 0
    aggregate_counts: Counter[str] = Counter()
    with InterruptHandler() as interrupt:
        while True:
            if interrupt.requested:
                log.info("interrupted; %d chunks ingested, leaving any in-flight "
                         "batches submitted (use --ingest <id> to drain later)",
                         chunk_idx)
                break
            if total_limit is not None and drained >= total_limit:
                log.info("--limit %d reached; stopping after %d chunks",
                         total_limit, chunk_idx)
                break

            remaining = fetch_pending_canonical_names(
                db.conn, normalizer_version=NORMALIZER_VERSION,
            )
            if not remaining:
                log.info("queue drained; all chunks ingested")
                break

            chunk_idx += 1
            this_chunk = chunk_size
            if total_limit is not None:
                this_chunk = min(chunk_size, total_limit - drained)
            log.info(
                "chunk %d: %d names pending; submitting up to %d",
                chunk_idx, len(remaining), this_chunk,
            )

            while True:
                if interrupt.requested:
                    break
                try:
                    outcome = submit_normalize_names_batch(
                        db.conn, provider=provider,
                        batches_dir=batches_dir, limit=this_chunk,
                    )
                    break
                except Exception as exc:
                    if not _is_enqueue_limit(exc):
                        raise
                    log.warning(
                        "enqueue-limit hit on chunk %d; sleeping %d min "
                        "and retrying: %s", chunk_idx, RATE_LIMIT_BACKOFF // 60, exc,
                    )
                    time.sleep(RATE_LIMIT_BACKOFF)
            if interrupt.requested:
                break

            batch_id = outcome.submission.batch_id
            log.info(
                "chunk %d submitted: batch %s (%d requests)",
                chunk_idx, batch_id, outcome.submission.request_count,
            )

            while True:
                if interrupt.requested:
                    break
                st = provider.status(batch_id)
                log.info("chunk %d status=%s (%d/%d)",
                         chunk_idx, st.state, st.completed, st.total)
                if st.state == "completed":
                    break
                if st.state in ("failed", "expired", "cancelled"):
                    log.error(
                        "chunk %d batch %s ended in state %s — stopping",
                        chunk_idx, batch_id, st.state,
                    )
                    from common.llm.sidecar import mark_failed
                    mark_failed(batches_dir / f"{batch_id}.json", state=st.state)
                    return 1
                time.sleep(poll_interval)
            if interrupt.requested:
                break

            counts = ingest_normalize_names_batch(
                conn=db.conn, provider=provider,
                batch_id=batch_id, batches_dir=batches_dir,
            )
            for k, v in counts.items():
                aggregate_counts[k] += v
            drained += outcome.submission.request_count
            log.info("chunk %d ingested: %s (drained %d total)",
                     chunk_idx, dict(counts), drained)

            # Park names that didn't clear ('noop' / parse error / provider
            # error / etc.) so they don't reappear in the next chunk or run.
            # Operator runs `normalize-names retry-failures` to unpark after
            # resolving the underlying blocker.
            stuck = park_attempted_names(
                db.conn, normalizer_version=NORMALIZER_VERSION,
                names=list(outcome.submitted_names),
            )
            db.conn.commit()
            if stuck:
                aggregate_counts["parked"] = aggregate_counts.get("parked", 0) + stuck
                log.info("chunk %d parked %d stuck names as pending_llm_tried",
                         chunk_idx, stuck)

    parked_total = aggregate_counts.get("parked", 0)
    if parked_total:
        log.info(
            "parked %d names as pending_llm_tried "
            "(run 'normalize-names retry-failures' to retry)",
            parked_total,
        )
    print_summary(
        f"normalize-names resolve-pending ({chunk_idx} chunks, {drained} drained)",
        {"all": aggregate_counts}, mode="applied",
    )
    return 0


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
    if getattr(args, "map_cmd", None) == "retry-failures":
        return run_map_retry_failures(args)
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


def run_normalize_names(args: argparse.Namespace) -> int:
    from ingredients.dedup.db import fetch_pending_canonical_names
    from ingredients.dedup.version import NORMALIZER_VERSION

    if getattr(args, "normalize_cmd", None) == "retry-failures":
        return run_normalize_names_retry_failures(args)

    if getattr(args, "normalize_cmd", None) == "resolve-pending":
        from ingredients.dedup.normalizer_llm import (
            run_phase2, submit_normalize_names_batch, ingest_normalize_names_batch,
        )
        from pathlib import Path

        BATCHES_DIR = Path("data/batches")

        # Validate flag combos
        if getattr(args, "batch", False) and args.provider != "openai":
            log.error("--batch requires --provider openai")
            return 2
        if getattr(args, "ingest", None) and not getattr(args, "batch", False):
            # --ingest implies --batch
            args.batch = True

        db = IngredientsDatabase()
        try:
            # ---- Batch ingest path (drain a previously-submitted batch) ----
            if getattr(args, "batch", False) and getattr(args, "ingest", None):
                from common.llm.openai_batch import OpenAIBatchProvider
                _model = getattr(args, "model", None)
                provider = (
                    OpenAIBatchProvider.from_env(model_id=_model)
                    if _model else OpenAIBatchProvider.from_env()
                )
                force = getattr(args, "force", False)
                return _run_dedup_ingest(
                    db, provider, args.ingest, force=force,
                    default_dir=BATCHES_DIR,
                )

            # ---- Pre-flight: count pending and confirm ----
            residuals = fetch_pending_canonical_names(db.conn, normalizer_version=NORMALIZER_VERSION)
            if not residuals:
                log.info("nothing pending; queue is empty")
                return 0
            log.info("Phase 2: %d distinct names pending. Top 20:", len(residuals))
            for n in residuals[:20]:
                log.info("  %s", n)
            if len(residuals) > 20:
                log.info("  ... and %d more", len(residuals) - 20)

            limit = getattr(args, "limit", None)
            chunk_size = getattr(args, "chunk_size", 2000)
            if getattr(args, "batch", False):
                target = (
                    f"at most {limit} of {len(residuals)}"
                    if limit is not None else f"all {len(residuals)}"
                )
                mode = (
                    f"OpenAI Batch API (50% off, ~24h SLA per chunk; "
                    f"chunk_size={chunk_size}, draining {target})"
                )
            else:
                mode = f"--provider {args.provider}"
            if not args.yes:
                sys.stderr.write(f"Proceed with {mode}? [y/N]: ")
                sys.stderr.flush()
                answer = sys.stdin.readline().strip().lower()
                if answer not in ("y", "yes"):
                    log.info("aborted by operator")
                    return 1

            # ---- Batch path: drain in chunks until queue/limit exhausted ----
            if getattr(args, "batch", False):
                from common.llm.openai_batch import OpenAIBatchProvider
                _model = getattr(args, "model", None)
                provider = (
                    OpenAIBatchProvider.from_env(model_id=_model)
                    if _model else OpenAIBatchProvider.from_env()
                )
                return _drain_dedup_in_chunks(
                    db, provider, BATCHES_DIR,
                    chunk_size=chunk_size,
                    total_limit=limit,
                    poll_interval=getattr(args, "poll_interval", 600),
                )

            # ---- Sync path (existing) ----
            _model = getattr(args, "model", None)
            if args.provider == "claude":
                from common.llm.claude import ClaudeProvider
                provider = ClaudeProvider.from_env(model_id=_model) if _model else ClaudeProvider.from_env()
            elif args.provider == "openai":
                from common.llm.openai import OpenAIProvider
                provider = OpenAIProvider.from_env(model_id=_model) if _model else OpenAIProvider.from_env()
            else:
                from common.llm.ollama import OllamaProvider
                provider = OllamaProvider.from_env(model_id=_model) if _model else OllamaProvider.from_env()
            limit = getattr(args, "limit", None)
            counts = run_phase2(db.conn, provider=provider, limit=limit)
            changes = {"all": Counter(counts)}
            print_summary(f"normalize-names resolve-pending ({args.provider}, {NORMALIZER_VERSION})",
                          changes, mode="applied")
            return 0
        finally:
            db.close()

    if getattr(args, "normalize_cmd", None) == "list-pending":
        db = IngredientsDatabase()
        try:
            limit = getattr(args, "limit", 50)
            residuals = fetch_pending_canonical_names(
                db.conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
            )
            for n in residuals:
                print(n)
            return 0
        finally:
            db.close()

    # Default: Phase 1
    if args.review:
        from ingredients.dedup.eval_set import run_eval as _run_dedup_eval
        report = _run_dedup_eval()
        return 0 if report.failed == 0 else 1

    db = IngredientsDatabase()
    try:
        if args.reset:
            # normalize-names operates on `recipes`, not recipe_ingredients.
            # Count rows that actually have normalized data to clear.
            except_version = getattr(args, "except_version", None)
            to_clear = db.conn.execute("""
                select count(*) from recipes
                 where canonical_name_source is not null
                   and (%s::text is null or site = %s)
                   and (%s::text is null or normalizer_version <> %s)
            """, (args.site, args.site, except_version, except_version)).fetchone()[0]
            scope = describe_reset_scope(
                site=args.site,
                except_version=except_version,
                older_than=getattr(args, "older_than", None),
            )
            if not confirm_reset(
                row_count=to_clear, scope_desc=scope,
                assume_yes=getattr(args, "yes", False),
            ):
                log.error("reset aborted")
                return 1
            db.conn.execute("""
                update recipes
                   set canonical_name = null,
                       canonical_name_source = null,
                       normalizer_version = null,
                       normalized_at = null
                 where (%s::text is null or site = %s)
                   and (%s::text is null or normalizer_version <> %s or normalizer_version is null)
            """, (args.site, args.site, except_version, except_version))
            db.conn.commit()
            log.info("cleared normalization columns")
            return 0
        from ingredients.dedup.normalizer import run_phase1
        counts = run_phase1(db.conn, site=args.site, limit=args.limit,
                            dry_run=args.dry_run)
        changes = {"all": Counter(counts)}
        mode = "dry-run" if args.dry_run else "applied"
        print_summary(f"normalize-names (Phase 1, {NORMALIZER_VERSION})", changes, mode=mode)
        return 0
    finally:
        db.close()


def run_cluster(args: argparse.Namespace) -> int:
    if getattr(args, "cluster_cmd", None) == "audit":
        from ingredients.dedup.audit import run_all_audits
        db = IngredientsDatabase()
        try:
            sigs = run_all_audits(db.conn)
            for name, rows in sigs.items():
                print(f"\n=== {name} ({len(rows)} rows) ===")
                for r in rows[:50]:
                    print(f"  {r}")
            return 0
        finally:
            db.close()

    if args.review:
        from ingredients.dedup.eval_set import run_eval as _run_dedup_eval
        report = _run_dedup_eval()
        return 0 if report.failed == 0 else 1

    db = IngredientsDatabase()
    try:
        if args.reset:
            if args.site:
                log.error(
                    "cluster --reset does not support --site scoping: recipe_clusters is "
                    "shared across sites. Either reset globally (omit --site) or null only "
                    "the recipes.cluster_id column manually."
                )
                return 2
            scope = describe_reset_scope(
                site=args.site,
                except_version=getattr(args, "except_version", None),
                older_than=getattr(args, "older_than", None),
            )
            if not confirm_reset(
                row_count=None, scope_desc=scope,
                assume_yes=getattr(args, "yes", False),
            ):
                log.error("reset aborted")
                return 1
            # Order matters: recipes.cluster_id has an FK to recipe_clusters.id,
            # so the FK references must be nulled out before we can DELETE the
            # cluster rows. Pre-image: also clear the role tags + variant_key
            # on the affected recipes.
            except_version = getattr(args, "except_version", None)
            if except_version:
                db.conn.execute("""
                    update recipe_ingredients
                       set role = null, role_source = null
                     where recipe_id in (
                         select id from recipes
                          where dedup_version <> %s or dedup_version is null
                     )
                """, (except_version,))
                db.conn.execute("""
                    update recipes
                       set cluster_id = null, variant_key = null, dedup_version = null
                     where dedup_version <> %s or dedup_version is null
                """, (except_version,))
                db.conn.execute("""
                    delete from recipe_clusters
                     where dedup_version <> %s or dedup_version is null
                """, (except_version,))
            else:
                db.conn.execute("""
                    update recipe_ingredients
                       set role = null, role_source = null
                """)
                db.conn.execute("""
                    update recipes
                       set cluster_id = null, variant_key = null, dedup_version = null
                """)
                db.conn.execute("delete from recipe_clusters")
            db.conn.commit()
            log.info("cleared cluster columns")
            return 0
        from ingredients.dedup.cluster import run_cluster_compute
        counts = run_cluster_compute(db.conn, site=args.site, limit=args.limit,
                                     dry_run=args.dry_run)
        changes = {"all": Counter(counts)}
        mode = "dry-run" if args.dry_run else "applied"
        print_summary("cluster", changes, mode=mode)
        return 0
    finally:
        db.close()


def run_promote_substances(args: argparse.Namespace) -> int:
    from ingredients.dedup.promote_substances import (
        candidate_promotions, promote_node,
    )
    db = IngredientsDatabase()
    try:
        cands = candidate_promotions(db.conn)
        if not cands:
            log.info("No candidates for promotion.")
            return 0
        for c in cands:
            print(f"\nCandidate: {c['display_name']} (slug={c['slug']}, current_node_kind={c['current_node_kind']})")
            print(f"  proposed: node_kind=NULL, is_cluster_node=true, default_role={c['proposed_default_role']}")
            if not args.yes:
                ans = input("Promote? [y/N/q] ").strip().lower()
                if ans == "q":
                    break
                if ans != "y":
                    continue
            promote_node(
                db.conn, slug=c["slug"],
                default_role=c["proposed_default_role"],
                promoter=os.environ.get("USER", "operator"),
            )
            log.info("Promoted %s.", c["slug"])
        return 0
    finally:
        db.close()


def run_dedup_all(args: argparse.Namespace) -> int:
    from ingredients.dedup.normalizer import run_phase1
    from ingredients.dedup.cluster import run_cluster_compute
    from ingredients.dedup.version import NORMALIZER_VERSION

    db = IngredientsDatabase()
    try:
        n = run_phase1(db.conn, site=args.site, limit=args.limit)
        changes_n = {"all": Counter(n)}
        print_summary("normalize-names", changes_n, mode="applied")

        c = run_cluster_compute(db.conn, site=args.site, limit=args.limit)
        changes_c = {"all": Counter(c)}
        print_summary("cluster", changes_c, mode="applied")
        return 0
    finally:
        db.close()


def run_recipegf_export_review_proposals(args: argparse.Namespace) -> int:
    from ingredients.recipegf.proposals import fetch_pending_proposals, mark_decided

    db = IngredientsDatabase()
    try:
        pending = fetch_pending_proposals(db.conn)
        if not pending:
            log.info("no pending recipegf proposals")
            return 0
        for p in pending:
            print()
            print(f"proposal #{p['id']}  cluster={p['cluster_id']}  "
                  f"{p['canonical_name']!r}")
            print(f"  reason:  {p['reason']}")
            print(f"  detail:  {p['detail']}")
            print(f"  source:  {p['source_url']}")
            answer = input("[r]esolved / re[j]ected / [s]kip: ").strip().lower()
            if answer == "r":
                mark_decided(db.conn, proposal_id=p["id"], status="resolved",
                             decided_by=args.decided_by)
                log.info("marked #%s resolved (re-run recipegf-export --reset to retry)", p["id"])
            elif answer == "j":
                mark_decided(db.conn, proposal_id=p["id"], status="rejected",
                             decided_by=args.decided_by)
                log.info("marked #%s rejected", p["id"])
            else:
                continue
        return 0
    finally:
        db.close()


def run_recipegf_export(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    from ingredients.recipegf.export import run_export
    from ingredients.recipegf.version import CONVERTER_VERSION

    if getattr(args, "recipegf_cmd", None) == "review-proposals":
        return run_recipegf_export_review_proposals(args)

    if args.review:
        # The converter is pure (no DB) — the eval runs against in-repo real
        # recipe fixtures, so unlike map/dedup --review it needs no TEST_DB_URL.
        from ingredients.recipegf.eval_set import run_eval
        report = run_eval()
        print("--- RecipeGF export eval ---")
        print(f"  passed: {report['passed']}")
        print(f"  failed: {report['failed']}")
        if report["failed"]:
            for c in report["cases"]:
                if not c["ok"]:
                    print(f"  {c['name']!r}: {c['detail']}")
            return 1
        return 0

    db = IngredientsDatabase()
    try:
        if args.reset:
            if args.site:
                log.error(
                    "recipegf-export --reset does not support --site scoping: "
                    "recipe_clusters is shared across sites. Reset globally "
                    "(omit --site) or clear the columns manually."
                )
                return 2
            from ingredients.recipegf.db import (
                clear_exported_rows, count_exported_rows,
            )
            to_clear = count_exported_rows(
                db.conn, except_version=args.except_version,
                older_than=args.older_than,
            )
            scope = describe_reset_scope(
                site=None, except_version=args.except_version,
                older_than=args.older_than,
            )
            if not confirm_reset(
                row_count=to_clear, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if to_clear:
                n = clear_exported_rows(
                    db.conn, except_version=args.except_version,
                    older_than=args.older_than,
                )
                db.conn.commit()
                log.info("cleared recipegf_* columns on %d clusters", n)
            return 0

        imported_at = datetime.now(timezone.utc).isoformat()
        counts = run_export(
            db.conn, imported_at=imported_at, site=args.site, limit=args.limit,
            dry_run=args.dry_run, out_dir=args.out,
        )
        mode = "dry-run" if args.dry_run else "applied"
        print_summary(
            f"RecipeGF export ({CONVERTER_VERSION})",
            {"all": Counter(counts)}, mode=mode,
        )
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
    _top_level_cmds = (
        "parse", "map", "normalize-names", "cluster",
        "promote-substances", "dedup-all", "recipegf-export", "--help", "-h",
    )
    if argv and argv[0] not in _top_level_cmds:
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
    if cmd == "normalize-names":
        return run_normalize_names(args)
    if cmd == "cluster":
        return run_cluster(args)
    if cmd == "promote-substances":
        return run_promote_substances(args)
    if cmd == "dedup-all":
        return run_dedup_all(args)
    if cmd == "recipegf-export":
        return run_recipegf_export(args)
    parser.error(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
