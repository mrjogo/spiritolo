from unittest.mock import MagicMock

from common.llm.openai import OpenAIProvider


def _fake_openai_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = reply_text
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    client.chat.completions.create.return_value = fake_resp
    return client


def test_resolve_returns_provider_result_with_model_id():
    client = _fake_openai_client('{"action": "chose", "node_id": 7}')
    p = OpenAIProvider(client=client, model_id="gpt-5-mini")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    # NUL-strip re-serializes with compact separators; the parsed dict is
    # what matters to downstream parse_response, not whitespace.
    import json as _json
    assert _json.loads(out.raw_text) == {"action": "chose", "node_id": 7}
    assert out.model_id == "gpt-5-mini"
    client.chat.completions.create.assert_called_once()
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "u"}
    # gpt-5-family needs ample headroom because reasoning tokens count
    # against this budget; 256 isn't enough and produces empty content.
    assert kwargs["max_completion_tokens"] == 2048
    assert kwargs["response_format"] == {"type": "json_object"}
    # gpt-5-family must pin reasoning_effort=minimal, otherwise the model
    # burns the budget thinking about a structured-retrieval prompt.
    assert kwargs["reasoning_effort"] == "minimal"


def test_resolve_omits_reasoning_effort_for_non_gpt5_models():
    """gpt-4o-mini and older models reject reasoning_effort with a 400.
    The provider must only set it for gpt-5-family models."""
    client = _fake_openai_client('{"action": "chose"}')
    p = OpenAIProvider(client=client, model_id="gpt-4o-mini")
    p.resolve(system_prompt="s", user_prompt="u")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs


def test_model_id_property_matches_constructor():
    p = OpenAIProvider(client=MagicMock(), model_id="gpt-4o-mini")
    assert p.model_id == "gpt-4o-mini"


def test_from_env_reads_api_key_and_constructs_client(monkeypatch):
    import openai

    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: captured.update(kw) or object())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

    p = OpenAIProvider.from_env()

    assert captured == {"api_key": "sk-env"}
    assert p.model_id == "gpt-5-mini"


def test_from_env_missing_key_raises(monkeypatch):
    import pytest

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider.from_env()


def test_from_env_accepts_base_url_http_client_and_explicit_key(monkeypatch):
    """DeepSeek reuses this path: an OpenAI-compatible base_url, an explicit key
    (no env read), and a pre-built direct-route http client."""
    import openai

    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: captured.update(kw) or object())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    http = object()

    p = OpenAIProvider.from_env(
        model_id="deepseek-chat",
        base_url="https://api.deepseek.com",
        http_client=http,
        api_key="sk-explicit",
        api_key_env="DEEPSEEK_API_KEY",
    )

    assert captured["api_key"] == "sk-explicit"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["http_client"] is http
    assert p.model_id == "deepseek-chat"
