"""Async-batch LLM provider Protocol.

Lifecycle: caller assembles BatchRequests, calls submit() (returns a
BatchSubmission with the provider's batch_id), later calls status() and
fetch_results() once status='completed'.

The provider is opaque to the row→prompt mapping; callers persist a sidecar
JSON file (see common.llm.sidecar) keyed on the batch_id that maps each
custom_id back to row identity.

Implementations: openai_batch.OpenAIBatchProvider. Future: claude batch.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BatchRequest:
    custom_id: str           # alphanumeric + _-, max 64 chars (OpenAI constraint)
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class BatchSubmission:
    batch_id: str
    provider: str            # 'openai'; written to sidecar so --ingest knows
    model_id: str
    request_count: int


@dataclass(frozen=True)
class BatchStatus:
    batch_id: str
    state: str               # 'in_progress' | 'completed' | 'failed' | 'expired' | 'cancelled'
    completed: int
    total: int


@dataclass(frozen=True)
class BatchResult:
    custom_id: str
    raw_text: str | None     # None on per-request failure
    error: str | None


class BatchProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def submit(self, requests: Iterable[BatchRequest]) -> BatchSubmission: ...

    def status(self, batch_id: str) -> BatchStatus: ...

    def fetch_results(self, batch_id: str) -> Iterable[BatchResult]: ...
