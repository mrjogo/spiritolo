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
    assert out.raw_text == '{"action": "chose", "node_id": 7}'
    assert out.model_id == "gpt-5-mini"
    client.chat.completions.create.assert_called_once()
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "u"}
    assert kwargs["max_completion_tokens"] == 256
    assert kwargs["response_format"] == {"type": "json_object"}


def test_model_id_property_matches_constructor():
    p = OpenAIProvider(client=MagicMock(), model_id="gpt-4o-mini")
    assert p.model_id == "gpt-4o-mini"
