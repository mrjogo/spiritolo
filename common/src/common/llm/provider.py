"""Sync LLM provider Protocol used by the per-row resolve loops in the
ingredient-map and name-normalization LLM tiers and in scraper classify.

Implementations live in sibling modules: claude.py, ollama.py, openai.py.
Tests inject stubs via the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider output. Caller parses with the flow's parse_response."""
    raw_text: str
    model_id: str           # e.g. 'claude-haiku-4-5', 'qwen3:14b', 'gpt-5-mini'
    prompt_tokens: int | None = None      # input tokens the provider billed, if reported
    completion_tokens: int | None = None  # output tokens generated, if reported


class LLMProvider(Protocol):
    """Anything that can answer a single prompt with structured JSON text."""

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
    ) -> ProviderResult: ...

    @property
    def model_id(self) -> str: ...
