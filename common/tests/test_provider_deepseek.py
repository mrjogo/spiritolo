"""DeepSeek provider. DeepSeek exposes an OpenAI-compatible Chat Completions API,
so this is a thin factory over ``OpenAIProvider`` pinned to DeepSeek's base URL,
default model, and API key — not a separate client implementation.
"""

from common.llm.deepseek import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL,
    build_deepseek_provider,
)
from common.llm.openai import OpenAIProvider


def test_build_targets_deepseek_base_url_and_model(monkeypatch):
    import openai

    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: captured.update(kw) or object())
    http = object()

    provider = build_deepseek_provider(api_key="sk-deepseek", http_client=http)

    assert isinstance(provider, OpenAIProvider)
    assert provider.model_id == DEEPSEEK_DEFAULT_MODEL == "deepseek-v4-flash"
    assert captured["api_key"] == "sk-deepseek"
    assert captured["base_url"] == DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert captured["http_client"] is http


def test_non_gpt5_model_omits_reasoning_effort(monkeypatch):
    """deepseek-v4-flash is not a gpt-5 model, so the OpenAI resolve path must not
    send ``reasoning_effort`` (DeepSeek would reject it)."""
    from unittest.mock import MagicMock

    client = MagicMock()
    choice = MagicMock()
    choice.message.content = '{"action": "abstain"}'
    client.chat.completions.create.return_value = MagicMock(choices=[choice])

    provider = OpenAIProvider(client=client, model_id=DEEPSEEK_DEFAULT_MODEL)
    provider.resolve(system_prompt="s", user_prompt="u")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
