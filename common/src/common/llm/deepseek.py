"""DeepSeek provider — a thin factory over ``OpenAIProvider``.

DeepSeek's API is OpenAI-compatible (same Chat Completions shape and Python
SDK), so we don't need a separate client: we point ``OpenAIProvider`` at
DeepSeek's base URL, default model, and API key. ``deepseek-v4-flash`` is not a
gpt-5 model, so the OpenAI resolve path already omits ``reasoning_effort``.

Two DeepSeek-specific quirks. Its API has JSON mode
(``response_format={"type": "json_object"}``) but no ``json_schema`` structured
output, so the provider is built with ``supports_json_schema=False``: a
``response_schema`` goes into the system prompt as text and JSON mode stays on.
And JSON mode requires the word "json" to appear somewhere in the prompt, or
the API errors; the chain's ``packing.ENVELOPE_INSTRUCTIONS`` (and the
appended schema text) always contain it.
"""

from __future__ import annotations

from .openai import OpenAIProvider

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


def build_deepseek_provider(
    *,
    api_key: str,
    http_client: object | None = None,
    model_id: str = DEEPSEEK_DEFAULT_MODEL,
) -> OpenAIProvider:
    """Build an ``OpenAIProvider`` pinned to DeepSeek's endpoint."""
    provider = OpenAIProvider.from_env(
        model_id=model_id,
        base_url=DEEPSEEK_BASE_URL,
        http_client=http_client,
        api_key=api_key,
        api_key_env="DEEPSEEK_API_KEY",
    )
    # DeepSeek's flash model thinks by default, which bills reasoning tokens at
    # the output rate and can crowd the packed reply out of max_tokens. Its
    # Thinking Mode doc gives the OpenAI-format toggle as an extra_body field.
    provider.extra_body = {"thinking": {"type": "disabled"}}
    provider.supports_json_schema = False
    return provider
