"""The local-vs-hosted provider proxy split, and the generic local tier.

The worker reaches barbot's local LLM server (LM Studio or Ollama) over a
Tailscale userspace SOCKS proxy, but hosted APIs (OpenAI / Claude / ScraperAPI)
must take the direct route — their traffic must not tunnel through barbot's
uplink. So only the local client reads ``TS_LOCAL_PROXY``; the hosted clients
are constructed with no proxy and with env-proxy inheritance severed
(``trust_env=False``), so a global ``ALL_PROXY`` / ``HTTPS_PROXY`` can't leak
them onto the tunnel.

The local tier is an OpenAI-compatible endpoint chosen by URL
(``LOCAL_LLM_BASE_URL``), so these tests also pin the request it sends.

Pure test: the httpx client is built through an injected factory that records
its kwargs (or a ``MockTransport`` that records requests) — no network.
"""
from __future__ import annotations

import json

import httpx
import pytest
from common.llm.openai import OpenAIProvider
from ingredients.worker.providers_local import (
    available_providers,
    build_claude_http_client,
    build_local_provider,
    build_openai_http_client,
    build_provider_for_run,
    local_base_url,
)

_HOSTED = (build_openai_http_client, build_claude_http_client)


class RecordingFactory:
    """Stand-in for ``httpx.Client`` that captures the kwargs it was built with."""

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return httpx.Client(**kwargs)


def _chat_reply(content: str) -> dict:
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
    }


class TransportFactory:
    """``httpx.Client`` factory over a ``MockTransport`` that records each
    request and answers with an OpenAI-shaped chat completion."""

    def __init__(self, content: str = '{"results": []}') -> None:
        self.requests: list[httpx.Request] = []
        self.kwargs: dict | None = None
        self._content = content

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=_chat_reply(self._content))

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        kwargs = {k: v for k, v in kwargs.items() if k != "proxy"}
        return httpx.Client(transport=httpx.MockTransport(self._handle), **kwargs)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


def test_local_client_uses_ts_proxy():
    env = {
        "TS_LOCAL_PROXY": "socks5://localhost:1055",
        "LOCAL_LLM_BASE_URL": "http://barbot:1234",
    }
    fac = RecordingFactory()
    provider = build_local_provider(client_factory=fac, env=env)

    assert fac.kwargs["proxy"] == "socks5://localhost:1055"
    assert str(provider.client.base_url).rstrip("/") == "http://barbot:1234/v1"


def test_hosted_clients_bypass_proxy():
    # TS_LOCAL_PROXY is present, but a hosted client must never read it.
    env = {"TS_LOCAL_PROXY": "socks5://localhost:1055"}
    for build in _HOSTED:
        fac = RecordingFactory()
        build(client_factory=fac, env=env)
        assert "proxy" not in fac.kwargs, f"{build.__name__} tunneled through the proxy"


def test_hosted_providers_for_run_bypass_proxy():
    # The full run path: the local tier tunnels, a hosted tier never does.
    env = {"TS_LOCAL_PROXY": "socks5://localhost:1055", "OPENAI_API_KEY": "sk-o",
           "DEEPSEEK_API_KEY": "sk-d"}
    fac = RecordingFactory()
    build_provider_for_run("local", None, env=env, client_factory=fac)
    assert fac.kwargs["proxy"] == "socks5://localhost:1055"
    for pid in ("openai", "deepseek"):
        fac = RecordingFactory()
        build_provider_for_run(pid, None, env=env, client_factory=fac)
        assert "proxy" not in fac.kwargs, f"{pid} tunneled through the proxy"


def test_no_global_all_proxy_leak():
    # A global ALL_PROXY / HTTPS_PROXY must not pull the hosted clients onto the
    # tunnel: they sever env-proxy inheritance.
    env = {"ALL_PROXY": "socks5://localhost:1055", "HTTPS_PROXY": "http://x:8080"}
    for build in _HOSTED:
        fac = RecordingFactory()
        build(client_factory=fac, env=env)
        assert fac.kwargs.get("trust_env") is False
        assert "proxy" not in fac.kwargs

    # The local client tunnels ONLY when TS_LOCAL_PROXY is set; it never inherits
    # a global ALL_PROXY either.
    fac = RecordingFactory()
    build_local_provider(client_factory=fac, env=env)
    assert "proxy" not in fac.kwargs
    assert fac.kwargs.get("trust_env") is False


@pytest.mark.parametrize(
    ("env", "want"),
    [
        ({"LOCAL_LLM_BASE_URL": "http://barbot:1234"}, "http://barbot:1234"),
        ({"LOCAL_LLM_BASE_URL": "http://barbot:1234/v1/"}, "http://barbot:1234"),
        # One-release fallback for the old Ollama variable.
        ({"OLLAMA_BASE_URL": "http://barbot:11434"}, "http://barbot:11434"),
        ({"LOCAL_LLM_BASE_URL": "http://a:1", "OLLAMA_BASE_URL": "http://b:2"}, "http://a:1"),
        ({}, "http://localhost:1234"),
    ],
)
def test_local_base_url(env, want):
    assert local_base_url(env) == want


def test_local_and_ollama_ids_build_the_same_openai_compatible_provider():
    env = {"LOCAL_LLM_BASE_URL": "http://barbot:1234"}
    for pid in ("local", "ollama"):  # `ollama` is the alias old job rows carry
        prov = build_provider_for_run(pid, "qwen/qwen3-14b", env=env)
        assert isinstance(prov, OpenAIProvider)
        assert prov.model_id == "qwen/qwen3-14b"
        assert prov.cost_per_call == 0  # unmetered


def test_local_model_falls_back_to_env_then_default():
    assert build_local_provider(env={"LOCAL_LLM_MODEL": "qwen/qwen3-14b"}).model_id == "qwen/qwen3-14b"
    assert build_local_provider(env={"LOCAL_LLM_MODEL": "x"}, model_id="y").model_id == "y"
    assert build_local_provider(env={}).model_id == "qwen3:14b"


def test_local_provider_posts_chat_completions():
    fac = TransportFactory('{"results": [{"id": "a", "answer": {}}]}')
    prov = build_local_provider(
        client_factory=fac, env={"LOCAL_LLM_BASE_URL": "http://barbot:1234"},
        model_id="qwen/qwen3-14b",
    )
    out = prov.resolve(system_prompt="sys json", user_prompt="usr")

    req = fac.requests[-1]
    assert str(req.url) == "http://barbot:1234/v1/chat/completions"
    body = fac.body()
    assert body["model"] == "qwen/qwen3-14b"
    assert body["messages"][0] == {"role": "system", "content": "sys json"}
    # LM Studio has no `json_object` mode: it is sent as a JSON-schema constraint
    # for "any object", which LM Studio and Ollama both enforce.
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}
    # Older runtimes read `max_tokens`, not `max_completion_tokens`.
    assert body["max_tokens"] == body["max_completion_tokens"]
    assert json.loads(out.raw_text) == {"results": [{"id": "a", "answer": {}}]}
    assert out.model_id == "qwen/qwen3-14b"


def test_local_provider_passes_a_json_schema_through():
    fac = TransportFactory()
    prov = build_local_provider(client_factory=fac, env={})
    schema = {"type": "json_schema",
              "json_schema": {"name": "answer", "schema": {"type": "object",
                              "properties": {"a": {"type": "string"}}}, "strict": True}}
    prov.client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "x"}], response_format=schema,
    )
    assert fac.body()["response_format"] == schema


def test_local_extra_body_is_merged_into_every_request():
    fac = TransportFactory()
    env = {"LOCAL_LLM_EXTRA_BODY": '{"chat_template_kwargs": {"enable_thinking": false}}'}
    prov = build_local_provider(client_factory=fac, env=env)
    prov.resolve(system_prompt="s json", user_prompt="u")
    assert fac.body()["chat_template_kwargs"] == {"enable_thinking": False}


def test_local_extra_body_must_be_a_json_object():
    with pytest.raises(ValueError, match="LOCAL_LLM_EXTRA_BODY"):
        build_local_provider(env={"LOCAL_LLM_EXTRA_BODY": "[1, 2]"})
    with pytest.raises(ValueError, match="LOCAL_LLM_EXTRA_BODY"):
        build_local_provider(env={"LOCAL_LLM_EXTRA_BODY": "not json"})


def test_available_providers_lists_local_always():
    assert available_providers({}) == ["local"]
    assert available_providers({"DEEPSEEK_API_KEY": "x"}) == ["local", "deepseek"]


def test_local_provider_turns_reasoning_off_by_default():
    fac = TransportFactory()
    build_local_provider(client_factory=fac, env={}).resolve(system_prompt="s json", user_prompt="u")
    assert fac.body()["reasoning_effort"] == "none"


def test_local_reasoning_effort_is_configurable_and_omittable():
    fac = TransportFactory()
    env = {"LOCAL_LLM_REASONING_EFFORT": "low"}
    build_local_provider(client_factory=fac, env=env).resolve(system_prompt="s json", user_prompt="u")
    assert fac.body()["reasoning_effort"] == "low"

    fac = TransportFactory()
    env = {"LOCAL_LLM_REASONING_EFFORT": ""}
    build_local_provider(client_factory=fac, env=env).resolve(system_prompt="s json", user_prompt="u")
    assert "reasoning_effort" not in fac.body()
