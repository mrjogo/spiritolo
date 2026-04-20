"""URL classifier: main runner, review mode, and sample subcommand.

Main run: asyncio pool of workers pulling unclassified rows, classifying each
via ollama, writing back to pages.content_type + classifications audit table.
"""

import asyncio
import logging
from typing import Awaitable, Callable

from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult

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
