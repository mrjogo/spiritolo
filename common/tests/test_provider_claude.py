from unittest.mock import MagicMock

from common.llm.claude import ClaudeProvider


def _fake_anthropic_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_message = MagicMock()
    fake_message.content = [MagicMock(type="text", text=reply_text)]
    client.messages.create.return_value = fake_message
    return client


def test_resolve_returns_provider_result_with_model_id():
    client = _fake_anthropic_client('{"action": "chose", "node_id": 7}')
    p = ClaudeProvider(client=client, model_id="claude-haiku-4-5")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    assert out.raw_text == '{"action": "chose", "node_id": 7}'
    assert out.model_id == "claude-haiku-4-5"
    client.messages.create.assert_called_once()
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert kwargs["messages"][0]["content"] == "u"
    # Haiku 4.5 thinks only when asked and rejects `effort`: send neither.
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs


def test_haiku_5_5_turns_thinking_off_at_low_effort():
    client = _fake_anthropic_client("{}")
    ClaudeProvider(client=client, model_id="claude-haiku-5-5").resolve(
        system_prompt="sys", user_prompt="u"
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "disabled"}
    assert kwargs["output_config"] == {"effort": "low"}
    # A full packed reply needs room: 256 truncated 10-item envelopes.
    assert kwargs["max_tokens"] == 2048


def test_empty_system_prompt_is_omitted():
    client = _fake_anthropic_client("{}")
    ClaudeProvider(client=client).resolve(system_prompt="", user_prompt="u")
    assert "system" not in client.messages.create.call_args.kwargs


def test_reply_text_skips_thinking_blocks():
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(type="thinking", text=""), MagicMock(type="text", text='{"ok": 1}')]
    client.messages.create.return_value = msg
    out = ClaudeProvider(client=client).resolve(system_prompt="s", user_prompt="u")
    assert out.raw_text == '{"ok": 1}'


def test_model_id_property_matches_constructor():
    p = ClaudeProvider(client=MagicMock(), model_id="claude-sonnet-4-6")
    assert p.model_id == "claude-sonnet-4-6"


def test_from_env_reads_api_key_and_constructs_client(monkeypatch):
    import anthropic

    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: captured.update(kw) or object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")

    p = ClaudeProvider.from_env()

    assert captured == {"api_key": "sk-env"}
    assert p.model_id == "claude-haiku-5-5"


def test_from_env_missing_key_raises(monkeypatch):
    import pytest

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeProvider.from_env()


def test_from_env_accepts_http_client_and_explicit_key(monkeypatch):
    import anthropic

    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: captured.update(kw) or object())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    http = object()

    p = ClaudeProvider.from_env(api_key="sk-explicit", http_client=http)

    assert captured["api_key"] == "sk-explicit"
    assert captured["http_client"] is http
    assert p.model_id == "claude-haiku-5-5"


def test_response_schema_sets_output_config_format():
    client = _fake_anthropic_client('{"a": "x"}')
    schema = {"type": "object", "properties": {"a": {"type": "string"}},
              "required": ["a"], "additionalProperties": False}
    ClaudeProvider(client=client, model_id="claude-haiku-4-5").resolve(
        system_prompt="sys", user_prompt="u", response_schema=schema
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["output_config"] == {"format": {"type": "json_schema", "schema": schema}}


def test_response_schema_keeps_haiku_5_5_effort():
    client = _fake_anthropic_client("{}")
    schema = {"type": "object"}
    ClaudeProvider(client=client).resolve(system_prompt="s", user_prompt="u", response_schema=schema)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["output_config"] == {
        "effort": "low", "format": {"type": "json_schema", "schema": schema},
    }


def test_no_schema_sends_no_output_config():
    client = _fake_anthropic_client("{}")
    ClaudeProvider(client=client, model_id="claude-haiku-4-5").resolve(system_prompt="s", user_prompt="u")
    assert "output_config" not in client.messages.create.call_args.kwargs


def test_haiku_5_5_turns_thinking_off_and_reads_the_text_block():
    """Haiku 5.5 thinks by default and puts a ThinkingBlock first; the provider
    must disable it (plus low effort) and still read the text block when one
    comes back anyway."""
    import types
    client = MagicMock()
    thinking = types.SimpleNamespace(type="thinking", thinking="")
    text = types.SimpleNamespace(type="text", text='{"label": "likely_junk"}')
    client.messages.create.return_value = MagicMock(content=[thinking, text])
    p = ClaudeProvider(client=client, model_id="claude-haiku-5-5")
    out = p.resolve(system_prompt="s", user_prompt="u", response_schema={"type": "object"})
    assert out.raw_text == '{"label": "likely_junk"}'
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "disabled"}
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_haiku_4_5_sends_no_thinking_parameter():
    client = _fake_anthropic_client('{"label": "x"}')
    ClaudeProvider(client=client, model_id="claude-haiku-4-5").resolve(system_prompt="s", user_prompt="u")
    kwargs = client.messages.create.call_args.kwargs
    assert "thinking" not in kwargs and "output_config" not in kwargs


def test_reply_without_text_block_is_an_error():
    import pytest, types
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[types.SimpleNamespace(type="thinking", thinking="")])
    with pytest.raises(ValueError):
        ClaudeProvider(client=client, model_id="claude-haiku-5-5").resolve(system_prompt="s", user_prompt="u")


def test_adaptive_thinking_sends_adaptive_low_effort_and_more_room():
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="text", text='{"ok": true}')]
    )
    p = ClaudeProvider(client=client, model_id="claude-haiku-5-5", thinking="adaptive")
    p.resolve(system_prompt="sys", user_prompt="u")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["max_tokens"] >= 8192


def test_from_env_rejects_unknown_thinking_mode(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import pytest
    with pytest.raises(ValueError):
        ClaudeProvider.from_env(thinking="sometimes")
