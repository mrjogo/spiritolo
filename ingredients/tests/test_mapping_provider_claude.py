from unittest.mock import MagicMock

from ingredients.mapping.llm_provider_claude import ClaudeProvider


def _fake_anthropic_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=reply_text)]
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
    assert kwargs["system"] == "sys"
    assert kwargs["messages"][0]["content"] == "u"


def test_model_id_property_matches_constructor():
    p = ClaudeProvider(client=MagicMock(), model_id="claude-sonnet-4-6")
    assert p.model_id == "claude-sonnet-4-6"
