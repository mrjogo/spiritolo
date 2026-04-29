"""Anthropic Claude provider for Phase 2.

Defaults to Haiku 4.5; the resolver may instantiate a Sonnet 4.6 instance
on retry for low-confidence cases (deferred — out of scope for v1 plan).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .llm_provider import ProviderResult

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256


@dataclass
class ClaudeProvider:
    client: object               # anthropic.Anthropic; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "ClaudeProvider":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or export before "
                "running `map resolve-pending --provider claude`."
            )
        return cls(client=anthropic.Anthropic(api_key=api_key), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        msg = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Anthropic returns a list of content blocks; the first one is text.
        text = msg.content[0].text
        return ProviderResult(raw_text=text, model_id=self.model_id)
