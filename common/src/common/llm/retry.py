"""Retry helper used by every flow that drains an LLM queue.

Used by:
  - mapping.llm_resolver.run_phase2
  - dedup.normalizer_llm.run_phase2
  - scraper.classify (when --provider != ollama, when batch=False)

The orchestrator owns the queue; this helper owns the per-call retry policy.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .provider import LLMProvider

log = logging.getLogger("common.llm.retry")


def resolve_with_retry(
    provider: LLMProvider, *, system_prompt: str, user_prompt: str,
    normalized_name: str, max_attempts: int = 3,
    parse_fn: Callable[[str], dict] | None = None,
) -> dict | None:
    """Call provider.resolve + parse the raw text; retry on any exception
    with exponential backoff. Returns the parsed action dict, or None if
    all attempts failed.

    parse_fn must validate and return a dict; raise on bad shape so retry
    can fire. Callers pass the flow's own parse_response (mapping, dedup,
    classify all have their own action vocabulary).
    """
    if parse_fn is None:
        raise TypeError("parse_fn is required; pass the flow's parse_response")
    for attempt in range(max_attempts):
        try:
            raw = provider.resolve(
                system_prompt=system_prompt, user_prompt=user_prompt,
            ).raw_text
            return parse_fn(raw)
        except Exception as exc:
            if attempt + 1 == max_attempts:
                log.error(
                    "LLM call exhausted retries for %r: %s",
                    normalized_name, exc,
                )
                return None
            sleep_for = 2 ** attempt   # 1s, 2s, 4s
            log.warning(
                "LLM call failed for %r (attempt %d/%d): %s — retrying in %ds",
                normalized_name, attempt + 1, max_attempts, exc, sleep_for,
            )
            time.sleep(sleep_for)
    return None
