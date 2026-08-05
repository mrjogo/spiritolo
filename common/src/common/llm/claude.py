"""Anthropic Claude provider (sync). Defaults to Haiku 4.5."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256


@dataclass
class ClaudeProvider:
    client: object               # anthropic.Anthropic; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(
        cls,
        *,
        model_id: str = DEFAULT_MODEL,
        http_client: object | None = None,
        api_key: str | None = None,
    ) -> "ClaudeProvider":
        """Build a provider over the Anthropic SDK. ``http_client`` injects a
        pre-built transport (the worker's direct-route client); ``api_key``
        overrides the ``ANTHROPIC_API_KEY`` env read."""
        import anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or export before "
                "using this provider."
            )
        client_kwargs: dict[str, object] = {"api_key": key}
        if http_client is not None:
            client_kwargs["http_client"] = http_client
        return cls(client=anthropic.Anthropic(**client_kwargs), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        # No `thinking` and no `output_config.effort` on purpose: on Haiku 4.5
        # extended thinking is opt-in (omitting `thinking` = no thinking, which
        # is what we want for structured retrieval), and the `effort` parameter
        # is rejected by Haiku 4.5 — setting either would be wrong here.
        msg = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = msg.content[0].text
        usage = getattr(msg, "usage", None)
        return ProviderResult(
            raw_text=text,
            model_id=self.model_id,
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
        )
