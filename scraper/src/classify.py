"""URL classifier: main runner, review mode, and sample subcommand.

Main run: asyncio pool of workers pulling unclassified rows, classifying each
via ollama, writing back to pages.content_type + classifications audit table.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Awaitable, Callable

from scraper.src.classify_prompt import PROMPT_VERSION
from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult, classify_url

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"

log = logging.getLogger(__name__)

ClassifyFn = Callable[..., Awaitable[ClassificationResult]]


async def classify_one(
    row: dict,
    classify_fn: ClassifyFn,
    db: Database,
    model: str,
    prompt_version: str,
) -> None:
    """Classify one row. Errors are logged and the row is left unclassified
    so a future run will retry it."""
    try:
        result = await classify_fn(
            url=row["url"],
            sitemap_source=row.get("sitemap_source"),
            model=model,
        )
    except Exception as e:
        log.warning("classify failed for id=%s url=%s: %s", row["id"], row["url"], e, exc_info=True)
        return

    db.record_classification(
        page_id=row["id"],
        label=result.label,
        model=model,
        prompt_version=prompt_version,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
    )


async def run_classify_pool(
    rows: list[dict],
    classify_fn: ClassifyFn,
    db: Database,
    model: str,
    prompt_version: str,
    concurrency: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Run classify_one over rows with at most `concurrency` in-flight calls.

    on_progress(done, total) is invoked after each row completes, so the CLI
    can render a progress bar without this module knowing anything about UI.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(rows)
    done = 0

    async def worker(r: dict):
        nonlocal done
        async with sem:
            await classify_one(r, classify_fn, db, model, prompt_version)
        done += 1
        if on_progress:
            on_progress(done, total)

    await asyncio.gather(*(worker(r) for r in rows))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="classify",
        description="Classify unclassified URLs in scraper.db via a local ollama model.",
    )
    p.add_argument("--site", help="Limit run to one site (matches pages.site).")
    p.add_argument("--limit", type=int, help="Stop after this many URLs (main run only).")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Concurrent in-flight ollama requests (default: 4).")
    p.add_argument("--model", default="qwen3:14b", help="Ollama model tag (default: qwen3:14b).")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to scraper.db.")
    p.add_argument("--batch-size", type=int, default=1000,
                   help="Rows pulled from DB per batch (keeps task-object memory bounded). Default: 1000.")
    p.add_argument("--review", action="store_true",
                   help="Run the prompt against the checked-in eval set instead of the DB.")
    p.add_argument("--sample", action="store_true",
                   help="Print N random (url, label, raw_response) rows for --site --category.")
    p.add_argument("--category", help="For --sample: which label to sample from.")
    p.add_argument("--n", type=int, default=10, help="For --sample: number of rows (default 10).")
    return p


def _progress(done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        pct = 100 * done / total if total else 0
        print(f"\r  {done}/{total} ({pct:.1f}%)", end="", flush=True)
        if done == total:
            print()


async def run_main(args: argparse.Namespace) -> int:
    """Main classify run, batched.

    We pull `--batch-size` rows at a time from the DB rather than loading all
    NULL rows up front. With ~521k unclassified URLs, materializing every row
    as an asyncio.Task would consume hundreds of MB of task-object memory.
    Batching keeps that bounded and is otherwise indistinguishable from a
    single big run because the work queue is just `content_type IS NULL`.
    """
    db = Database(args.db)
    remaining = args.limit  # None means "no limit"
    grand_total = 0

    while True:
        if remaining is not None and remaining <= 0:
            break
        batch_limit = args.batch_size if remaining is None else min(args.batch_size, remaining)
        rows = db.get_unclassified(site=args.site, limit=batch_limit)
        if not rows:
            break

        if grand_total == 0:
            print(f"Classifying via {args.model} (concurrency={args.concurrency}, "
                  f"batch_size={args.batch_size}, prompt={PROMPT_VERSION})")
        print(f"Batch of {len(rows)} (processed so far: {grand_total})")

        await run_classify_pool(
            rows=rows,
            classify_fn=classify_url,
            db=db,
            model=args.model,
            prompt_version=PROMPT_VERSION,
            concurrency=args.concurrency,
            on_progress=_progress,
        )

        grand_total += len(rows)
        if remaining is not None:
            remaining -= len(rows)

    if grand_total == 0:
        print("No unclassified rows. Done.")
    else:
        print(f"Done. Classified {grand_total} rows.")
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)

    if args.sample:
        return _run_sample(args)
    if args.review:
        return asyncio.run(_run_review(args))
    return asyncio.run(run_main(args))


def _run_sample(args: argparse.Namespace) -> int:
    # Implemented in Task 12.
    raise NotImplementedError("--sample is added in a later task")


async def _run_review(args: argparse.Namespace) -> int:
    # Implemented in Task 11.
    raise NotImplementedError("--review is added in a later task")


if __name__ == "__main__":
    sys.exit(main())
