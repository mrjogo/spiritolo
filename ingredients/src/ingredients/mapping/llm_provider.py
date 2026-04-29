"""Provider interface used by Phase 2.

Implementations: llm_provider_claude.py, llm_provider_ollama.py.

Tests inject StubProvider via the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider output. Caller parses with prompt.parse_response."""
    raw_text: str
    model_id: str           # e.g. 'claude-haiku-4-5' or 'qwen3:14b'


class LLMProvider(Protocol):
    """Anything that can answer a single prompt with structured JSON text."""

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
    ) -> ProviderResult: ...

    @property
    def model_id(self) -> str: ...
