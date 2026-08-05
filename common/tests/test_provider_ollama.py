from unittest.mock import MagicMock, Mock

from common.llm.ollama import OllamaProvider


def test_ollama_captures_token_counts():
    from common.llm.ollama import OllamaProvider
    resp = Mock(status_code=200)
    resp.json.return_value = {"response": "{}", "prompt_eval_count": 142, "eval_count": 188}
    client = Mock()
    client.post.return_value = resp
    r = OllamaProvider(client=client).resolve(system_prompt="", user_prompt="x")
    assert r.prompt_tokens == 142 and r.completion_tokens == 188


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
    assert payload["think"] is False  # qwen3 thinking mode disabled


def test_ollama_sends_num_predict_cap():
    from common.llm.ollama import OllamaProvider, DEFAULT_NUM_PREDICT
    resp = Mock(status_code=200)
    resp.json.return_value = {"response": "{}"}
    client = Mock()
    client.post.return_value = resp
    OllamaProvider(client=client).resolve(system_prompt="", user_prompt="x")
    body = client.post.call_args.kwargs["json"]
    assert body["num_predict"] == DEFAULT_NUM_PREDICT and body["think"] is False


def test_model_id_property_matches_constructor():
    p = OllamaProvider(client=MagicMock(), model_id="llama3:8b")
    assert p.model_id == "llama3:8b"


def _resp(*, status_code=200, response_text=""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = {"response": response_text}
    r.raise_for_status.return_value = None
    return r


def test_auto_pulls_model_then_retries_when_generate_404s():
    """A missing model makes /api/generate return 404 ('try pulling it first').
    With auto_pull on, the provider pulls the model and retries the generate."""
    client = MagicMock()
    client.post.side_effect = [
        _resp(status_code=404),                       # generate: model not present
        _resp(status_code=200),                       # pull: download completes
        _resp(status_code=200, response_text='{"action": "abstain"}'),  # generate retry
    ]
    p = OllamaProvider(client=client, model_id="qwen3:14b", base_url="http://barbot:11434")

    out = p.resolve(system_prompt="sys", user_prompt="u")

    assert out.raw_text == '{"action": "abstain"}'
    urls = [c.args[0] for c in client.post.call_args_list]
    assert urls == [
        "http://barbot:11434/api/generate",
        "http://barbot:11434/api/pull",
        "http://barbot:11434/api/generate",
    ]
    pull_payload = client.post.call_args_list[1].kwargs["json"]
    assert pull_payload["model"] == "qwen3:14b"


def test_no_auto_pull_when_disabled_surfaces_the_404():
    client = MagicMock()
    client.post.return_value = _resp(status_code=404)
    client.post.return_value.raise_for_status.side_effect = RuntimeError("404")
    p = OllamaProvider(client=client, model_id="qwen3:14b", auto_pull=False)

    import pytest

    with pytest.raises(RuntimeError):
        p.resolve(system_prompt="s", user_prompt="u")
    # Only the generate call — never a pull.
    assert client.post.call_count == 1
