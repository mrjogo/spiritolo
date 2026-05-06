"""URL classifier: main runner, review mode, and sample subcommand.

Main run: opens a pipeline_runs row, a ThreadPoolExecutor of workers pull
unclassified rows, classify each via the chosen LLMProvider, UPSERT
classify_url_runs (latest-only per page) with the label + prompt_version +
snapshot of the prior pages.content_type, then update pages.content_type.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common.cli_common import (
    add_reset_args, confirm_reset, describe_reset_scope,
)
from common.progress import make_progress
from common.summary import print_summary

from scraper.classify_prompt import LABELS, PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from scraper.db import Database
from scraper.ollama_client import classify_url

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_EVAL_PATH = Path(__file__).resolve().parent.parent / "eval" / "classify-urls.jsonl"

log = logging.getLogger(__name__)


def classify_one(
    row: dict,
    provider,
    db: Database,
    prompt_version: str,
    run_id: int | None = None,
) -> bool:
    """Classify one row. Errors are logged and the row is left unclassified
    so a future run will retry it.

    Returns True if the row was classified and written, False on any error.
    """
    try:
        result = classify_url(
            url=row["url"],
            sitemap_source=row.get("sitemap_source"),
            provider=provider,
        )
    except Exception as e:
        log.warning("classify failed for id=%s url=%s: %s", row["id"], row["url"], e, exc_info=True)
        return False

    db.record_classify_url(
        page_id=row["id"],
        run_id=run_id,
        label=result.label,
        model=provider.model_id,
        prompt_version=prompt_version,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
        pages_content_type_before=row.get("content_type"),
    )
    return True


def run_classify_pool(
    rows: list[dict],
    provider,
    db: Database,
    prompt_version: str,
    concurrency: int = 4,
    on_progress=None,
    run_id: int | None = None,
) -> int:
    """Run classify_one over rows with at most `concurrency` in-flight calls.

    on_progress(done, total) is invoked after each row completes, so the CLI
    can render a progress bar without this module knowing anything about UI.

    Returns the count of successfully classified rows (failures are swallowed
    by classify_one; this number lets callers detect zero-progress batches).
    """
    total = len(rows)
    done = 0
    successes = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {
            ex.submit(classify_one, r, provider, db, prompt_version, run_id): r
            for r in rows
        }
        for fut in as_completed(futures):
            ok = fut.result()
            if ok:
                successes += 1
            done += 1
            if on_progress:
                on_progress(done, total)
    return successes


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="classify",
        description="Classify unclassified URLs in scraper.db via an LLM provider.",
    )
    p.add_argument("--site", help="Limit run to one site (matches pages.site).")
    p.add_argument("--limit", type=int, help="Stop after this many URLs (main run only).")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Concurrent in-flight provider requests (default: 4).")
    p.add_argument(
        "--provider", choices=["ollama", "claude", "openai"], default="ollama",
        help="LLM provider for classification (default: ollama, free local).",
    )
    p.add_argument(
        "--model", default="qwen3:14b",
        help=(
            "Model id for the chosen provider (default: qwen3:14b for ollama). "
            "For claude pass e.g. claude-haiku-4-5; for openai pass e.g. gpt-5-mini."
        ),
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to scraper.db.")
    p.add_argument("--batch-size", type=int, default=1000,
                   help="Rows pulled from DB per batch (keeps task-object memory bounded). Default: 1000.")
    p.add_argument("--review", action="store_true",
                   help="Run the prompt against the checked-in eval set instead of the DB.")
    p.add_argument("--sample", action="store_true",
                   help="Print N random (site, url, label, raw) rows. Optionally filter "
                        "with --site and/or --category, or look up specific URLs with --urls.")
    p.add_argument("--category", help="For --sample: filter to this label.")
    p.add_argument("--n", type=int, default=10, help="For --sample: number of rows (default 10).")
    p.add_argument("--urls", nargs="+",
                   help="For --sample: look up these specific URLs instead of sampling. "
                        "Overrides --site/--category/--n.")
    p.add_argument(
        "--batch", action="store_true",
        help="Use OpenAI Batch API. Only valid with --provider openai.",
    )
    p.add_argument(
        "--ingest", metavar="BATCH_ID", default=None,
        help="Ingest a previously submitted classify batch. Implies --batch.",
    )
    p.add_argument(
        "--wait", action="store_true",
        help="With --batch, poll until completed and ingest in one command.",
    )
    p.add_argument(
        "--poll-interval", type=int, default=600,
        help="With --wait, seconds between status polls (default: 600).",
    )
    add_reset_args(p, stage="classify_url_runs")
    return p


def _build_provider(args: argparse.Namespace):
    """Instantiate the chosen sync LLM provider."""
    provider_name = getattr(args, "provider", "ollama") or "ollama"
    model = getattr(args, "model", None)
    if provider_name == "ollama":
        from common.llm.ollama import OllamaProvider
        return OllamaProvider.from_env(model_id=model) if model else OllamaProvider.from_env()
    if provider_name == "claude":
        from common.llm.claude import ClaudeProvider
        return ClaudeProvider.from_env(model_id=model) if model else ClaudeProvider.from_env()
    if provider_name == "openai":
        from common.llm.openai import OpenAIProvider
        return OpenAIProvider.from_env(model_id=model) if model else OpenAIProvider.from_env()
    raise ValueError(f"unknown provider {provider_name!r}")


def run_main(args: argparse.Namespace) -> int:
    """Main classify run, batched.

    We pull `--batch-size` rows at a time from the DB rather than loading all
    NULL rows up front. With ~521k unclassified URLs, materializing every row
    as a future would consume hundreds of MB of task-object memory.
    Batching keeps that bounded and is otherwise indistinguishable from a
    single big run because the work queue is just `content_type IS NULL`.

    If a batch produces zero successful classifications (e.g. ollama is down),
    we abort rather than spin forever on the same NULL rows.
    """
    db = Database(args.db)
    remaining = args.limit  # None means "no limit"
    grand_total = 0
    exit_code = 0

    provider = _build_provider(args)

    overall_total = db.count_unclassified(site=args.site)
    if args.limit is not None:
        overall_total = min(overall_total, args.limit)

    progress = make_progress(total=overall_total)
    changes: dict[str, Counter] = {}

    def adapter(batch_done: int, _batch_total: int) -> None:
        # The pool reports within-batch progress; translate to cumulative so
        # the shared progress callback's ETA is based on total work, not
        # per-batch fractions.
        progress(grand_total + batch_done)

    run_id = db.start_run(
        stage="classify_url",
        site=args.site,
        args={
            "limit": args.limit, "batch_size": args.batch_size,
            "model": provider.model_id, "concurrency": args.concurrency,
            "prompt_version": PROMPT_VERSION,
        },
    )

    try:
        while True:
            if remaining is not None and remaining <= 0:
                break
            batch_limit = args.batch_size if remaining is None else min(args.batch_size, remaining)
            rows = db.get_unclassified(site=args.site, limit=batch_limit)
            if not rows:
                break

            if grand_total == 0:
                scope = f"site={args.site}" if args.site else "all sites"
                log.info(
                    "classifying %s URLs (%s) via %s (concurrency=%d, batch_size=%d, prompt=%s)",
                    f"{overall_total:,}", scope, provider.model_id,
                    args.concurrency, args.batch_size, PROMPT_VERSION,
                )

            # Accumulate per-site / per-label counts by reading back what was
            # written this batch. Cheap because we already paid the round-trip
            # to write them.
            batch_urls = [r["url"] for r in rows]
            successes = run_classify_pool(
                rows=rows,
                provider=provider,
                db=db,
                prompt_version=PROMPT_VERSION,
                concurrency=args.concurrency,
                on_progress=adapter,
                run_id=run_id,
            )
            _accumulate_changes(db, batch_urls, changes)

            if successes == 0:
                print(
                    f"ERROR: batch of {len(rows)} produced zero classifications. "
                    "Check provider connectivity. Aborting to avoid an infinite loop.",
                    file=sys.stderr,
                )
                exit_code = 1
                break

            grand_total += len(rows)
            if remaining is not None:
                remaining -= len(rows)

        print_summary("Classify", changes)
        summary_dict = {site_key: dict(counter) for site_key, counter in changes.items()}
        db.finish_run(run_id, summary={
            "per_site": summary_dict, "total": grand_total, "exit_code": exit_code,
        })
    finally:
        db.close()
    return exit_code


def _accumulate_changes(
    db: Database, urls: list[str], changes: dict[str, Counter]
) -> None:
    """Read the post-batch content_type for the URLs just processed and fold
    them into the per-site Counter. URLs that are still NULL (errors) are
    counted under 'classify_error'."""
    if not urls:
        return
    placeholders = ",".join("?" for _ in urls)
    rows = db.conn.execute(
        f"SELECT site, content_type FROM pages WHERE url IN ({placeholders})",
        urls,
    ).fetchall()
    for row in rows:
        label = row["content_type"] or "classify_error"
        changes.setdefault(row["site"], Counter())[label] += 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    args = build_arg_parser().parse_args(argv)

    if args.sample:
        return _run_sample(args)
    if args.review:
        if args.batch:
            print("ERROR: --review is sync-only; cannot combine with --batch", file=sys.stderr)
            return 2
        return _run_review(args)
    if args.reset:
        rc = _do_reset(args)
        if rc != 0:
            return rc

    if args.batch and args.provider != "openai":
        print("ERROR: --batch requires --provider openai", file=sys.stderr)
        return 2
    if args.ingest and not args.batch:
        # --ingest implies --batch
        args.batch = True
    if args.wait and args.ingest:
        print("ERROR: --wait and --ingest are mutually exclusive", file=sys.stderr)
        return 2

    if args.batch:
        return run_batch(args)
    return run_main(args)


def _do_reset(args: argparse.Namespace) -> int:
    """classify --reset: deletes classify_url_runs rows AND nulls
    pages.content_type for the same rows, atomically. Both are required —
    the work queue gates on `content_type IS NULL`, so dropping the eval
    row alone wouldn't actually re-queue anything."""
    db = Database(args.db)
    try:
        to_delete = db.count_eval_rows(
            "classify_url_runs",
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
            n = db.reset_classify_url(
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            log.info("cleared %d classify_url_runs rows (and nulled content_type)", n)
        return 0
    finally:
        db.close()


def load_eval_set(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def run_review(eval_path: Path, provider) -> int:
    entries = load_eval_set(eval_path)
    correct = 0
    failures: list[tuple[dict, str]] = []
    for e in entries:
        try:
            result = classify_url(
                url=e["url"], sitemap_source=e.get("sitemap_source"),
                provider=provider,
            )
            predicted = result.label
        except Exception as err:
            predicted = f"ERROR: {err}"
        expected = e["expected"]
        if predicted == expected:
            correct += 1
        else:
            failures.append((e, predicted))

    total = len(entries)
    print(f"{correct}/{total} correct ({100*correct/total:.1f}%)")
    if failures:
        print("\nFailures:")
        for e, predicted in failures:
            print(f"  {e['url']}")
            print(f"    expected:  {e['expected']}")
            print(f"    predicted: {predicted}")
    return 0 if correct == total else 1


def run_sample(
    db_path: str | Path,
    site: str | None = None,
    category: str | None = None,
    n: int = 10,
    urls: list[str] | None = None,
) -> int:
    db = Database(db_path)
    try:
        if urls:
            rows = db.get_classify_url_for_urls(urls)
        else:
            rows = db.sample_classify_url(site=site, label=category, n=n)
    finally:
        db.close()
    if not rows:
        scope = []
        if site:
            scope.append(f"site={site}")
        if category:
            scope.append(f"category={category}")
        scope_str = " ".join(scope) if scope else "any"
        print(f"No classifications found ({scope_str})")
        return 0
    for r in rows:
        site_col = r.get("site") or "(not in DB)"
        label_col = r.get("label") or "(unclassified)"
        print(f"{site_col:<14} {label_col:<22} {r['url']}")
        if r.get("raw_response"):
            print(f"    raw: {r['raw_response']}")
    return 0


def _run_sample(args: argparse.Namespace) -> int:
    return run_sample(
        db_path=args.db,
        site=args.site,
        category=args.category,
        n=args.n,
        urls=args.urls,
    )


def _run_review(args: argparse.Namespace) -> int:
    return run_review(eval_path=DEFAULT_EVAL_PATH, provider=_build_provider(args))


# ---------------------------------------------------------------------------
# Batch (OpenAI Batch API) path
# ---------------------------------------------------------------------------

from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)


def submit_classify_batch(
    db: Database,
    *,
    provider: BatchProvider,
    batches_dir: Path,
    site: str | None,
    limit: int | None,
) -> BatchSubmitOutcome:
    """Submit unclassified pages as an OpenAI batch."""
    rows = db.get_unclassified(site=site, limit=limit)
    if not rows:
        raise RuntimeError("nothing pending; queue is empty")
    total = len(rows)

    log.info("building %d prompts…", total)
    payload = []
    for r in rows:
        user = build_user_message(r["url"], r.get("sitemap_source"))
        payload.append((r["url"], SYSTEM_PROMPT, user))

    log.info("submitting %d-request batch to %s…", total, provider.model_id)
    return submit_batch(
        provider=provider, rows=payload,
        to_request=lambda i, p: BatchRequest(
            custom_id=f"r{i}", system_prompt=p[1], user_prompt=p[2],
        ),
        row_to_id=lambda p: p[0],     # the URL
        flow="scraper.classify.url",
        version_constant=PROMPT_VERSION,
        batches_dir=batches_dir,
    )


def ingest_classify_batch(
    *,
    db: Database,
    provider: BatchProvider,
    batch_id: str,
    batches_dir: Path,
    run_id: int | None = None,
) -> dict[str, int]:
    """Ingest results from a previously submitted classify batch."""
    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        url = row_id
        if error or raw_text is None:
            log.warning("classify batch error for %s: %s", url, error)
            return
        try:
            payload = json.loads(raw_text)
            label = payload.get("label")
            if label not in LABELS:
                log.warning("classify batch invalid label %r for %s", label, url)
                return
        except Exception as exc:
            log.warning("classify batch parse failed for %s: %s", url, exc)
            return

        page_row = db.conn.execute(
            "SELECT id, content_type FROM pages WHERE url = ?", (url,)
        ).fetchone()
        if page_row is None:
            log.warning("classify batch URL no longer in pages: %s", url)
            return
        db.record_classify_url(
            page_id=page_row["id"],
            run_id=run_id,
            label=label,
            model=provider.model_id,
            prompt_version=PROMPT_VERSION,
            raw_response=raw_text,
            latency_ms=0,    # batch path: latency not meaningful
            pages_content_type_before=page_row["content_type"],
        )

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="scraper.classify.url",
        version_constant=PROMPT_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )


def run_batch(args: argparse.Namespace) -> int:
    import time

    from common.interrupt import InterruptHandler
    from common.llm.openai_batch import OpenAIBatchProvider

    BATCHES_DIR = Path("data/batches")

    db = Database(args.db)
    try:
        provider_kwargs = (
            {"model_id": args.model}
            if args.model and args.model != "qwen3:14b"
            else {}
        )
        provider = OpenAIBatchProvider.from_env(**provider_kwargs)

        if args.ingest:
            counts = ingest_classify_batch(
                db=db, provider=provider, batch_id=args.ingest,
                batches_dir=BATCHES_DIR,
            )
            print_summary(
                f"Classify ingest ({args.ingest})",
                {"all": Counter(counts)},
            )
            return 0

        outcome = submit_classify_batch(
            db, provider=provider, batches_dir=BATCHES_DIR,
            site=args.site, limit=args.limit,
        )
        print(
            f"submitted batch {outcome.submission.batch_id} "
            f"({outcome.submission.request_count} requests, model={outcome.submission.model_id})"
        )
        print(f"sidecar: {outcome.sidecar_path}")

        if args.wait:
            log.info("polling batch %s every %ds…", outcome.submission.batch_id, args.poll_interval)
            with InterruptHandler() as interrupt:
                while True:
                    if interrupt.requested:
                        log.info("interrupted; batch remains submitted, run --ingest later")
                        return 0
                    st = provider.status(outcome.submission.batch_id)
                    log.info("status=%s (%d/%d)", st.state, st.completed, st.total)
                    if st.state == "completed":
                        break
                    if st.state in ("failed", "expired", "cancelled"):
                        log.error("batch ended in state %s", st.state)
                        return 1
                    time.sleep(args.poll_interval)
            counts = ingest_classify_batch(
                db=db, provider=provider, batch_id=outcome.submission.batch_id,
                batches_dir=BATCHES_DIR,
            )
            print_summary(
                f"Classify ingest ({outcome.submission.batch_id})",
                {"all": Counter(counts)},
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
