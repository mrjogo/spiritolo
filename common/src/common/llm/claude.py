"""Anthropic Claude provider (sync). Defaults to Haiku 4.5.

Thinking: Haiku 4.5 only thinks when asked, so the request says nothing about
it. Haiku 5.5 thinks by default (adaptive) and would spend the small token
budget reasoning about a one-field answer and return a ``thinking`` block
first, so for it the request turns thinking off and pins low effort. The reply
is read from its first ``text`` block either way.
"""

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

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
        response_schema: dict | None = None,
    ) -> ProviderResult:
        # No `thinking` and no `output_config.effort` on purpose: on Haiku 4.5
        # extended thinking is opt-in (omitting `thinking` = no thinking, which
        # is what we want for structured retrieval), and the `effort` parameter
        # is rejected by Haiku 4.5 — setting either would be wrong here.
        kwargs: dict[str, object] = {}
        if _thinks_by_default(self.model_id):
            kwargs["thinking"] = {"type": "disabled"}
            kwargs.setdefault("output_config", {})["effort"] = "low"
        if response_schema is not None:
            # Structured outputs: the reply is constrained to the schema.
            kwargs.setdefault("output_config", {})["format"] = {
                "type": "json_schema", "schema": response_schema,
            }
        msg = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            **kwargs,
        )
        text = _first_text(msg.content)
        return ProviderResult(raw_text=text, model_id=self.model_id)


def _thinks_by_default(model_id: str) -> bool:
    """Haiku 5.x runs adaptive thinking unless told not to; ``disabled`` is
    accepted there (at effort ``high`` or below). The 4.x models don't think
    unless asked, and the Opus/Sonnet 5.5 line rejects ``disabled``."""
    return model_id.startswith("claude-haiku-5")


def _first_text(content: list) -> str:
    """The reply text: the first ``text`` block, skipping ``thinking`` blocks."""
    for block in content:
        if getattr(block, "type", None) == "text" or (
            getattr(block, "type", None) is None and hasattr(block, "text")
        ):
            return block.text
    raise ValueError(f"no text block in reply: {[getattr(b, 'type', '?') for b in content]}")
