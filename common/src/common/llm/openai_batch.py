"""OpenAI Batch API provider. 50% off real-time, ~24h SLA.

Lifecycle:
  submit()       — uploads a JSONL of requests, creates a batch, returns batch_id.
  status()       — polls the batch's status field.
  fetch_results()— downloads the output JSONL once status == 'completed'.

custom_id discipline: caller picks short alphanumeric IDs (max 64 chars,
[a-zA-Z0-9_-]). Persistence of custom_id → row identity is the caller's
responsibility (see common.llm.sidecar).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from .batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission

DEFAULT_MODEL = "gpt-5-mini"
# gpt-5-family charges reasoning tokens against max_completion_tokens; see
# common.llm.openai.OpenAIProvider for the full rationale. 2048 leaves
# headroom; reasoning_effort='minimal' (set below for gpt-5*) keeps the
# model from burning the budget on a structured-retrieval prompt.
DEFAULT_MAX_TOKENS = 2048
DEFAULT_COMPLETION_WINDOW = "24h"


def _is_gpt5_family(model_id: str) -> bool:
    return model_id.startswith("gpt-5")


@dataclass
class OpenAIBatchProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OpenAIBatchProvider":
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env or export before "
                "running --provider openai --batch."
            )
        return cls(client=openai.OpenAI(api_key=api_key), model_id=model_id)

    def submit(self, requests: Iterable[BatchRequest]) -> BatchSubmission:
        # Build JSONL body in memory (uses are bounded — tens of thousands
        # of small prompts, low MB).
        lines = []
        count = 0
        body_kwargs: dict = {
            "model": self.model_id,
            "max_completion_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if _is_gpt5_family(self.model_id):
            body_kwargs["reasoning_effort"] = "minimal"
        for r in requests:
            lines.append(json.dumps({
                "custom_id": r.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    **body_kwargs,
                    "messages": [
                        {"role": "system", "content": r.system_prompt},
                        {"role": "user", "content": r.user_prompt},
                    ],
                },
            }))
            count += 1
        body = ("\n".join(lines) + "\n").encode()
        file_obj = self.client.files.create(
            file=body,
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=file_obj.id,
            endpoint="/v1/chat/completions",
            completion_window=DEFAULT_COMPLETION_WINDOW,
        )
        return BatchSubmission(
            batch_id=batch.id, provider="openai",
            model_id=self.model_id, request_count=count,
        )

    def status(self, batch_id: str) -> BatchStatus:
        b = self.client.batches.retrieve(batch_id)
        return BatchStatus(
            batch_id=batch_id, state=b.status,
            completed=b.request_counts.completed,
            total=b.request_counts.total,
        )

    def fetch_results(self, batch_id: str) -> Iterator[BatchResult]:
        b = self.client.batches.retrieve(batch_id)
        if b.status != "completed":
            raise RuntimeError(
                f"batch {batch_id} status is {b.status!r}, not 'completed'"
            )
        if not b.output_file_id:
            raise RuntimeError(f"batch {batch_id} has no output_file_id")
        resp = self.client.files.content(b.output_file_id)
        text = getattr(resp, "text", None)
        if text is None:
            text = resp.read().decode() if hasattr(resp, "read") else str(resp)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            custom_id = row.get("custom_id", "")
            err = row.get("error")
            if err:
                yield BatchResult(
                    custom_id=custom_id, raw_text=None,
                    error=err.get("message", "unknown error"),
                )
                continue
            choices = (
                row.get("response", {})
                   .get("body", {})
                   .get("choices", [])
            )
            content = choices[0].get("message", {}).get("content") if choices else None
            # gpt-5-mini occasionally emits literal NUL (0x00) bytes in
            # otherwise-valid JSON output, especially around weird unicode in
            # ingredient strings. PostgreSQL TEXT columns reject NUL bytes
            # outright (psycopg.DataError) — strip them at the provider edge
            # so downstream writers don't have to know about it.
            if content is not None:
                content = content.replace("\x00", "")
            yield BatchResult(custom_id=custom_id, raw_text=content, error=None)
