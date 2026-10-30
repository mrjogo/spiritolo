"""Request packing for the provider chain.

An LLM tier answers many items in one prompt call. Packing chunks the pending
items into groups of `pack_size`, builds one packed request per chunk (a JSON
envelope of {id, input} rows), calls the underlying `LLMProvider.resolve` once
per chunk, then unpacks the response **by custom id** — so re-mapping outputs to
inputs is order-independent. Items the provider drops or errors on are parked.

The wire format lives here so the FakeProvider (a hermetic stand-in for a real
LLM) and the unpacker agree on encoding without either hardcoding the other.
``ENVELOPE_INSTRUCTIONS`` is the same contract spelled out for a real model: the
chain prepends it to every stage's system prompt, and ``envelope_schema`` wraps a
stage's per-item answer schema into the schema of the whole packed response.
"""
from __future__ import annotations

import json
import re
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


ENVELOPE_INSTRUCTIONS = """\
You answer a batch of independent items in one reply.

The user message is a JSON object {"items": [{"id": "<id>", "input": <item input>}, ...]}.
Answer each item on its own, following the task description below, and reply with
exactly one json object of this shape:

{"results": [{"id": "<the item's id, copied exactly>", "answer": <your answer for that item>}, ...]}

Rules for the envelope:
- Include every id from "items" exactly once, and never invent an id.
- "answer" is the per-item JSON object the task below describes.
- When you cannot answer an item, use the task's own abstain answer for it. Do
  not drop the item and do not add an "error" key.
- Output JSON only: no prose, no markdown fences.
"""


def envelope_schema(answer_schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema of a packed response whose per-item answers match
    ``answer_schema``. Strict-mode shaped (every property required, no extra
    properties), which OpenAI's structured outputs demand."""
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "answer": answer_schema,
                    },
                    "required": ["id", "answer"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def chunk(items: list[Item], pack_size: int) -> list[list[Item]]:
    """Split items into groups of at most `pack_size` (>= 1)."""
    if pack_size < 1:
        raise ValueError(f"pack_size must be >= 1, got {pack_size}")
    return [items[i : i + pack_size] for i in range(0, len(items), pack_size)]


def encode_request(items: list[Item]) -> str:
    """Serialize a chunk into the packed user-prompt envelope. Payloads go in
    as JSON values (a dict stays an object), never as a Python repr."""
    return json.dumps(
        {"items": [{"id": it.id, "input": it.payload} for it in items]},
        ensure_ascii=False,
        default=str,
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


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def decode_response(raw_text: str) -> dict[str, Any]:
    """Unpack a packed response into {id: answer} for the items that succeeded.

    Ids that errored or are absent are simply not present in the returned map;
    the caller parks them. A real model's reply is read leniently: a single
    markdown fence is stripped, a bare ``results`` list is accepted, and text
    that isn't the envelope at all (truncated JSON, a bare per-item object)
    decodes to ``{}`` so the whole pack parks instead of failing the run.
    """
    text = (raw_text or "").strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    try:
        doc = json.loads(text)
    except ValueError:
        return {}
    results = doc.get("results") if isinstance(doc, dict) else doc
    if not isinstance(results, list):
        return {}
    return {
        str(row["id"]): row["answer"]
        for row in results
        if isinstance(row, dict) and "id" in row and "answer" in row
    }
