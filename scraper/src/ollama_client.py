"""Thin async wrapper around ollama's chat API for URL classification.

One request per URL. Structured output via the `format` parameter prevents
malformed responses; the model can only return JSON matching RESPONSE_SCHEMA."""

import json
import time
from dataclasses import dataclass

from ollama import AsyncClient

from scraper.src.classify_prompt import (
    LABELS,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_message,
)


@dataclass
class ClassificationResult:
    label: str
    raw_response: str
    latency_ms: int


async def classify_url(
    url: str,
    sitemap_source: str | None,
    model: str,
    host: str | None = None,
) -> ClassificationResult:
    """Ask ollama to classify one URL. Returns ClassificationResult or raises.

    Raises ValueError for malformed or out-of-enum responses. Transport errors
    bubble up from the ollama library unchanged so the caller can decide
    retry policy.
    """
    client = AsyncClient(host=host)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(url, sitemap_source)},
    ]
    start = time.monotonic()
    resp = await client.chat(
        model=model,
        messages=messages,
        format=RESPONSE_SCHEMA,
        options={"temperature": 0, "num_predict": 50},
        think=False,
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    raw = resp["message"]["content"]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON from model: {raw!r}") from e

    label = payload.get("label")
    if label not in LABELS:
        raise ValueError(f"invalid label {label!r} (raw={raw!r})")

    return ClassificationResult(label=label, raw_response=raw, latency_ms=latency_ms)
