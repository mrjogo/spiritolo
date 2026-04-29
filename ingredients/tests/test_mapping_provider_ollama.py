from unittest.mock import MagicMock

from ingredients.mapping.llm_provider_ollama import OllamaProvider


def _fake_httpx_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"response": reply_text}
    fake_resp.raise_for_status.return_value = None
    client.post.return_value = fake_resp
    return client


def test_resolve_posts_to_generate_endpoint_and_returns_text():
    client = _fake_httpx_client('{"action": "abstain"}')
    p = OllamaProvider(client=client, model_id="qwen3:14b", base_url="http://localhost:11434")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    assert out.raw_text == '{"action": "abstain"}'
    assert out.model_id == "qwen3:14b"

    client.post.assert_called_once()
    args = client.post.call_args
    assert args.args[0].endswith("/api/generate")
    payload = args.kwargs["json"]
    assert payload["model"] == "qwen3:14b"
    assert payload["system"] == "sys"
    assert payload["prompt"] == "u"
    assert payload["stream"] is False


def test_model_id_property_matches_constructor():
    p = OllamaProvider(client=MagicMock(), model_id="llama3:8b")
    assert p.model_id == "llama3:8b"
