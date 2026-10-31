"""Anthropic Claude provider (sync). Default model from ``common.providers.pricing``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from common.providers.pricing import DEFAULT_MODEL as _DEFAULTS

from .provider import ProviderResult

DEFAULT_MODEL = _DEFAULTS["anthropic"]
# Room for a full packed reply (10 items' answers in one envelope).
DEFAULT_MAX_TOKENS = 2048
_NON_TEXT = ("thinking", "redacted_thinking")


THINKING_MODES = ("disabled", "adaptive")
# Thinking counts toward max_tokens on Haiku 5.5, so an adaptive request gets
# more room than the thinking-off default.
ADAPTIVE_MAX_TOKENS = 8192


def _reasoning_off(model_id: str) -> dict[str, object]:
    """Request kwargs that turn reasoning off for structured retrieval.

    Haiku 5.5 thinks by default (adaptive, effort ``medium``); ``disabled`` is
    accepted at effort ``high`` or below, so pin effort ``low`` with it. Haiku
    4.5 (old runs) thinks only when asked and rejects ``effort``, so it gets
    nothing. Other models aren't offered as tiers; leave them at their defaults
    rather than send a setting they may reject.
    """
    if model_id.startswith("claude-haiku-5"):
        return {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    return {}


@dataclass
class ClaudeProvider:
    client: object               # anthropic.Anthropic; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    # "disabled" (the default: structured retrieval needs no reasoning) or
    # "adaptive" (the model decides; Anthropic's Haiku 5.5 guide says to compare
    # the two on your own evals, and that adaptive tends to score higher).
    thinking: str = "disabled"

    @classmethod
    def from_env(
        cls,
        *,
        model_id: str = DEFAULT_MODEL,
        http_client: object | None = None,
        api_key: str | None = None,
        thinking: str = "disabled",
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
        if thinking not in THINKING_MODES:
            raise ValueError(f"thinking must be one of {THINKING_MODES}, got {thinking!r}")
        return cls(client=anthropic.Anthropic(**client_kwargs), model_id=model_id, thinking=thinking)

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
        response_schema: dict | None = None,
    ) -> ProviderResult:
        kwargs: dict[str, object] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if self.thinking == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": "low"}
            kwargs["max_tokens"] = max(self.max_tokens, ADAPTIVE_MAX_TOKENS)
        else:
            kwargs.update(_reasoning_off(self.model_id))
        if system_prompt:
            # The stage prompt is identical across a run's calls: cache it.
            # (Below the model's minimum cacheable length it simply isn't.)
            kwargs["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]
        if response_schema is not None:
            # Structured outputs: the reply is constrained to the schema.
            kwargs.setdefault("output_config", {})["format"] = {
                "type": "json_schema", "schema": response_schema,
            }
        msg = self.client.messages.create(**kwargs)
        return ProviderResult(raw_text=_first_text(msg.content), model_id=self.model_id)


def _first_text(content: list) -> str:
    """The reply's first text block. A reply that is all thinking (no text) is a
    provider error, not an empty answer: raise so the caller records it instead
    of parsing an empty string."""
    for block in content:
        if getattr(block, "type", None) not in _NON_TEXT and hasattr(block, "text"):
            return block.text
    raise ValueError(
        f"no text block in reply: {[getattr(b, 'type', '?') for b in content]}"
    )
