"""URL classifier: main runner, review mode, and sample subcommand.

Main run: asyncio pool of workers pulling unclassified rows, classifying each
via ollama, writing back to pages.content_type + classifications audit table.
"""

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
        log.warning("classify failed for id=%s url=%s: %s", row["id"], row["url"], e)
        return

    db.record_classification(
        page_id=row["id"],
        label=result.label,
        model=model,
        prompt_version=prompt_version,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
    )
