"""Request packing for the provider chain.

An LLM tier answers many items in one prompt call. Packing chunks the pending
items into groups of `pack_size`, builds one packed request per chunk (a JSON
envelope of {id, text} rows), calls the underlying `LLMProvider.resolve` once
per chunk, then unpacks the response **by custom id** — so re-mapping outputs to
inputs is order-independent. Items the provider drops or errors on are parked.

The wire format lives here so the FakeProvider (a hermetic stand-in for a real
LLM) and the unpacker agree on encoding without either hardcoding the other.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Item:
    """One unit of work flowing through the chain.

    `id` is the custom id the packed request/response key off (order-independent
    re-mapping). `payload` is the stage's input (e.g. an ingredient name).
    """

    id: str
    payload: Any = None


def chunk(items: list[Item], pack_size: int) -> list[list[Item]]:
    """Split items into groups of at most `pack_size` (>= 1)."""
    if pack_size < 1:
        raise ValueError(f"pack_size must be >= 1, got {pack_size}")
    return [items[i : i + pack_size] for i in range(0, len(items), pack_size)]


def encode_request(items: list[Item]) -> str:
    """Serialize a chunk into the packed user-prompt envelope."""
    return json.dumps(
        {"items": [{"id": it.id, "text": str(it.payload)} for it in items]}
    )


def decode_request(user_prompt: str) -> list[str]:
    """Extract the ordered custom ids from a packed request (used by fakes)."""
    return [row["id"] for row in json.loads(user_prompt)["items"]]


def encode_response(rows: list[dict[str, Any]]) -> str:
    """Serialize per-item result rows into the packed response envelope.

    Each row is {"id": id, "answer": <output>} on success or
    {"id": id, "error": <str>} on a per-item failure.
    """
    return json.dumps({"results": rows})


def decode_response(raw_text: str) -> dict[str, Any]:
    """Unpack a packed response into {id: answer} for the items that succeeded.

    Ids that errored or are absent are simply not present in the returned map;
    the caller parks them.
    """
    results = json.loads(raw_text).get("results", [])
    return {row["id"]: row["answer"] for row in results if "answer" in row}


def run_packed(
    provider: Any,
    items: list[Item],
    pack_size: int,
    *,
    system_prompt: str = "",
) -> tuple[dict[str, Any], list[str], int]:
    """Resolve `items` through an LLM `provider` in packed chunks.

    Returns (resolved, parked, calls):
      - resolved: {id: structured output} for items the provider answered,
      - parked:   ids the provider dropped or errored on (order preserved),
      - calls:    number of provider.resolve invocations (== ceil(N/pack_size)).
    """
    resolved: dict[str, Any] = {}
    parked: list[str] = []
    calls = 0
    for group in chunk(items, pack_size):
        result = provider.resolve(
            system_prompt=system_prompt, user_prompt=encode_request(group)
        )
        calls += 1
        answers = decode_response(result.raw_text)
        for it in group:
            if it.id in answers:
                resolved[it.id] = answers[it.id]
            else:
                parked.append(it.id)
    return resolved, parked, calls
