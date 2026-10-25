"""OpenAI sync provider. Default model from ``common.providers.pricing``.

For batch (50% off, ~24h SLA), see openai_batch.py.

gpt-5- and gpt-6-family models reason by default, charging reasoning tokens
against `max_completion_tokens`. Our prompts are pure structured retrieval and
need no reasoning, so we pin `reasoning_effort='none'` — which disables the
reasoning trace entirely (GPT-5.1+ and gpt-6) rather
than merely minimizing it. That also frees the whole 2048-token budget for the JSON output;
without disabling it, gpt-5.4-mini routinely returned empty content with
finish_reason='length'.

Structured output: with a ``response_schema`` the request carries
``response_format={"type": "json_schema", ..., "strict": True}``, so the reply
is guaranteed to match it. An endpoint that only has JSON mode (DeepSeek, see
deepseek.py) sets ``supports_json_schema=False``: it keeps ``json_object`` and
gets the schema as text appended to the system prompt instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from common.providers.pricing import DEFAULT_MODEL as _DEFAULTS

from .provider import ProviderResult

DEFAULT_MODEL = _DEFAULTS["openai"]
DEFAULT_MAX_TOKENS = 2048

# Model-id prefix -> the reasoning_effort value that turns reasoning off.
# Models outside these families (gpt-4o, DeepSeek's) reject the parameter.
_REASONING_OFF: dict[str, str] = {"gpt-5": "none", "gpt-6": "none"}


def _reasoning_effort_off(model_id: str) -> str | None:
    """The reasoning_effort that disables reasoning on ``model_id``, or ``None``
    when the model takes no reasoning_effort at all."""
    return next((v for p, v in _REASONING_OFF.items() if model_id.startswith(p)), None)


def response_format_for(response_schema: dict | None) -> dict:
    """The Chat Completions ``response_format`` for a schema (strict structured
    output), or plain JSON mode when there is none."""
    if response_schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": response_schema, "strict": True},
    }


def schema_as_text(system_prompt: str, response_schema: dict | None) -> str:
    """``system_prompt`` with the schema spelled out, for JSON-mode-only APIs."""
    if response_schema is None:
        return system_prompt
    return (
        system_prompt
        + "\n\nYour reply must be a json object matching this JSON schema:\n"
        + json.dumps(response_schema)
    )


@dataclass
class OpenAIProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    # Vendor-specific request fields sent as the SDK's ``extra_body`` (e.g. a
    # thinking-mode switch on an OpenAI-compatible API).
    extra_body: dict | None = None
    # False for an OpenAI-compatible API without json_schema response_format.
    supports_json_schema: bool = True

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

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
        response_schema: dict | None = None,
    ) -> ProviderResult:
        if self.supports_json_schema:
            response_format = response_format_for(response_schema)
        else:
            system_prompt = schema_as_text(system_prompt, response_schema)
            response_format = response_format_for(None)
        kwargs = {
            "model": self.model_id,
            "max_completion_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
        }
        effort = _reasoning_effort_off(self.model_id)
        if effort is not None:
            kwargs["reasoning_effort"] = effort  # reasoning off for structured retrieval
        if self.extra_body:
            kwargs["extra_body"] = dict(self.extra_body)
        resp = self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        # See common.llm.openai_batch._strip_nul_from_json_text for why.
        from .openai_batch import _strip_nul_from_json_text
        text = _strip_nul_from_json_text(text) or ""
        return ProviderResult(raw_text=text, model_id=self.model_id)
