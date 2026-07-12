"""FakeProvider — the hermetic LLM seam for the provider chain.

Implements the existing `common.llm.provider.LLMProvider` Protocol
(`resolve(*, system_prompt, user_prompt) -> ProviderResult`) so the chain and
its packing path exercise real code with zero network / live model. Answers a
packed prompt from `canned_map` (id -> structured output); ids in `raises_for`
come back errored so the chain parks exactly them; `cost_per_call` is what the
chain's cost accounting reads per call. `calls` is observable so tests can prove
short-circuiting (zero calls) and pack-count (ceil(N/k)).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from common.llm.provider import ProviderResult

from . import packing


@dataclass
class FakeProvider:
    canned_map: dict[str, Any]
    cost_per_call: int = 0
    raises_for: Iterable[str] = field(default_factory=frozenset)
    model_id: str = "fake-model"
    calls: int = 0

    def __post_init__(self) -> None:
        self.raises_for = frozenset(self.raises_for)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.calls += 1
        ids = packing.decode_request(user_prompt)
        rows: list[dict[str, Any]] = []
        # Emit each chunk's answers in reversed order to prove the unpacker
        # re-maps by id, not by position.
        for item_id in reversed(ids):
            if item_id in self.raises_for:
                rows.append({"id": item_id, "error": "fake-forced-failure"})
            elif item_id in self.canned_map:
                rows.append({"id": item_id, "answer": self.canned_map[item_id]})
            else:
                rows.append({"id": item_id, "error": "no-canned-answer"})
        return ProviderResult(
            raw_text=packing.encode_response(rows), model_id=self.model_id
        )
