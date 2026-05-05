"""OpenAI sync provider. Defaults to gpt-5-mini.

For batch (50% off, ~24h SLA), see openai_batch.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_MAX_TOKENS = 256


@dataclass
class OpenAIProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OpenAIProvider":
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env or export before "
                "running --provider openai."
            )
        return cls(client=openai.OpenAI(api_key=api_key), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        resp = self.client.chat.completions.create(
            model=self.model_id,
            max_completion_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return ProviderResult(raw_text=text, model_id=self.model_id)
