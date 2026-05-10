"""Sync wrapper that asks an LLMProvider to classify one URL.

Prompt assembly stays here (in scraper, where the prompt module lives).
The LLM call itself goes through common.llm.LLMProvider, so any sync
provider — Ollama, Claude, OpenAI — can drive classify.
"""

import json
import time
from dataclasses import dataclass

from common.llm.provider import LLMProvider

from scraper.classify_prompt import (
    LABELS,
    SYSTEM_PROMPT,
    build_user_message,
)


@dataclass
class ClassificationResult:
    label: str
    raw_response: str
    latency_ms: int


def classify_url(
    *,
    url: str,
    sitemap_source: str | None,
    provider: LLMProvider,
) -> ClassificationResult:
    """Ask `provider` to classify one URL. Returns ClassificationResult or raises.

    Raises ValueError for malformed JSON or out-of-enum responses.
    Transport errors bubble up from the underlying provider unchanged so the
    caller can decide retry policy.
    """
    user = build_user_message(url, sitemap_source)
    start = time.monotonic()
    result = provider.resolve(system_prompt=SYSTEM_PROMPT, user_prompt=user)
    latency_ms = int((time.monotonic() - start) * 1000)
    raw = result.raw_text

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON from model: {raw!r}") from e

    label = payload.get("label")
    if label not in LABELS:
        raise ValueError(f"invalid label {label!r} (raw={raw!r})")

    return ClassificationResult(label=label, raw_response=raw, latency_ms=latency_ms)
