"""OpenAI sync provider. Defaults to gpt-5.4-mini.

For batch (50% off, ~24h SLA), see openai_batch.py.

gpt-5-family models reason by default, charging reasoning tokens against
`max_completion_tokens`. Our prompts are pure structured retrieval and need no
reasoning, so we pin `reasoning_effort='none'` — which disables the reasoning
trace entirely (GPT-5.1+, including the default gpt-5.4-mini) rather than merely
minimizing it. That also frees the whole 2048-token budget for the JSON output;
without disabling it, gpt-5.4-mini routinely returned empty content with
finish_reason='length'.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_MAX_TOKENS = 2048


def _is_gpt5_family(model_id: str) -> bool:
    """gpt-5/gpt-5-mini/gpt-5-nano accept reasoning_effort. Older models error."""
    return model_id.startswith("gpt-5")


@dataclass
class OpenAIProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(
        cls,
        *,
        model_id: str = DEFAULT_MODEL,
        base_url: str | None = None,
        http_client: object | None = None,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> "OpenAIProvider":
        """Build a provider over the OpenAI SDK.

        ``base_url`` targets an OpenAI-compatible endpoint (DeepSeek reuses this
        with ``https://api.deepseek.com``); ``http_client`` injects a pre-built
        transport (the worker's direct-route client); ``api_key`` overrides the
        env read (else ``api_key_env`` is consulted).
        """
        import openai
        key = api_key or os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(
                f"{api_key_env} not set. Add it to .env or export before using "
                "this provider."
            )
        client_kwargs: dict[str, object] = {"api_key": key}
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        if http_client is not None:
            client_kwargs["http_client"] = http_client
        return cls(client=openai.OpenAI(**client_kwargs), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        kwargs = {
            "model": self.model_id,
            "max_completion_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if _is_gpt5_family(self.model_id):
            kwargs["reasoning_effort"] = "none"  # reasoning off for structured retrieval
        resp = self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        # See common.llm.openai_batch._strip_nul_from_json_text for why.
        from .openai_batch import _strip_nul_from_json_text
        text = _strip_nul_from_json_text(text) or ""
        return ProviderResult(raw_text=text, model_id=self.model_id)
