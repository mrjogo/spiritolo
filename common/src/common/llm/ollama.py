"""Ollama provider (sync). Calls the local /api/generate endpoint over HTTP."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "qwen3:14b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0
# Pulling a model is a one-time multi-GB download the first time a model is used
# on a host, so it needs a far longer budget than a generate call.
DEFAULT_PULL_TIMEOUT = 1800.0


@dataclass
class OllamaProvider:
    client: object               # httpx.Client; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    # Ollama's /api/generate 404s ("model not found, try pulling it first") when
    # the model isn't present on the host. With auto_pull on we pull it once and
    # retry, so a fresh host self-provisions instead of erroring the whole job.
    auto_pull: bool = True

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OllamaProvider":
        import httpx
        base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return cls(client=client, model_id=model_id, base_url=base_url)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        resp = self._generate(system_prompt, user_prompt)
        if getattr(resp, "status_code", None) == 404 and self.auto_pull:
            self._pull()
            resp = self._generate(system_prompt, user_prompt)
        resp.raise_for_status()
        text = resp.json().get("response", "")
        return ProviderResult(raw_text=text, model_id=self.model_id)

    def _generate(self, system_prompt: str, user_prompt: str):
        return self.client.post(
            self.base_url.rstrip("/") + "/api/generate",
            json={
                "model": self.model_id,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
            },
        )

    def _pull(self) -> None:
        """Download the model onto the Ollama host (blocking, ~minutes first
        time). Streaming off so the call returns once the pull completes."""
        resp = self.client.post(
            self.base_url.rstrip("/") + "/api/pull",
            json={"model": self.model_id, "stream": False},
            timeout=DEFAULT_PULL_TIMEOUT,
        )
        resp.raise_for_status()
