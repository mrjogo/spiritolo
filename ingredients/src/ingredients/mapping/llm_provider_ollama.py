"""Ollama provider for Phase 2.

Calls the local /api/generate endpoint over HTTP. No streaming.
The classify pipeline already pulls qwen3:14b; reuse that model here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .llm_provider import ProviderResult

DEFAULT_MODEL = "qwen3:14b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0


@dataclass
class OllamaProvider:
    client: object               # httpx.Client; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OllamaProvider":
        import httpx
        base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return cls(client=client, model_id=model_id, base_url=base_url)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        url = self.base_url.rstrip("/") + "/api/generate"
        resp = self.client.post(
            url,
            json={
                "model": self.model_id,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        return ProviderResult(raw_text=text, model_id=self.model_id)
