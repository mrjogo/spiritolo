"""DeepSeek provider — a thin factory over ``OpenAIProvider``.

DeepSeek's API is OpenAI-compatible (same Chat Completions shape and Python
SDK), so we don't need a separate client: we point ``OpenAIProvider`` at
DeepSeek's base URL, default model, and API key. ``deepseek-chat`` is not a
gpt-5 model, so the OpenAI resolve path already omits ``reasoning_effort``.

One DeepSeek-specific quirk to keep in mind: JSON mode
(``response_format={"type": "json_object"}``, which the OpenAI path always
sends) requires the word "json" to appear somewhere in the prompt, or the API
errors. The map/parse system prompts describe a JSON contract, so this holds —
watch for it if you wire DeepSeek into a stage with a prompt that doesn't.
"""

from __future__ import annotations

from .openai import OpenAIProvider

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"


def build_deepseek_provider(
    *,
    api_key: str,
    http_client: object | None = None,
    model_id: str = DEEPSEEK_DEFAULT_MODEL,
) -> OpenAIProvider:
    """Build an ``OpenAIProvider`` pinned to DeepSeek's endpoint."""
    return OpenAIProvider.from_env(
        model_id=model_id,
        base_url=DEEPSEEK_BASE_URL,
        http_client=http_client,
        api_key=api_key,
        api_key_env="DEEPSEEK_API_KEY",
    )
