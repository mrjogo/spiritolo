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
from ingredients.worker.local_profiles import LOCAL_MODEL_PROFILES
from ingredients.worker.providers import ProviderChain, ProviderUnavailable
from ingredients.worker.providers_local import (
    LocalLLMError,
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


def test_local_ttl_is_sent_per_request():
    fac = TransportFactory()
    build_local_provider(client_factory=fac, env={}).resolve(system_prompt="s json", user_prompt="u")
    assert fac.body()["ttl"] == 300

    fac = TransportFactory()
    env = {"LOCAL_LLM_TTL": ""}
    build_local_provider(client_factory=fac, env=env).resolve(system_prompt="s json", user_prompt="u")
    assert "ttl" not in fac.body()


class HandlerFactory(TransportFactory):
    """A transport whose answer (or failure) is a callable of the request."""

    def __init__(self, handler) -> None:
        super().__init__()
        self._handler = handler

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def _refuse(request):
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


def test_server_down_is_a_clear_fatal_error():
    prov = build_local_provider(
        client_factory=HandlerFactory(_refuse), env={"LOCAL_LLM_BASE_URL": "http://barbot:1234"}
    )
    with pytest.raises(LocalLLMError) as info:
        prov.resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal
    assert "not reachable at http://barbot:1234" in str(info.value)
    assert "LM Studio running" in str(info.value)


def test_server_down_fails_the_run_once_with_that_message():
    # Fatal, so the chain neither retries nor parks pack after pack: the first
    # pack raises ProviderUnavailable carrying the explanation.
    fac = HandlerFactory(_refuse)
    prov = build_local_provider(client_factory=fac, env={"LOCAL_LLM_BASE_URL": "http://barbot:1234"})
    chain = ProviderChain(tiers=[("local", prov)], pack_size=1)
    from common.providers.packing import Item

    with pytest.raises(ProviderUnavailable, match="LM Studio running"):
        chain.resolve([Item(id=str(i), payload="x") for i in range(5)], system_prompt="p")
    assert len(fac.requests) == 1


def test_model_that_cannot_load_names_the_model():
    def not_found(request):
        return httpx.Response(404, json={"error": {"message": "Model qwen9 not found"}})

    prov = build_local_provider(client_factory=HandlerFactory(not_found), env={}, model_id="qwen9")
    with pytest.raises(LocalLLMError) as info:
        prov.resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal and info.value.status_code == 404
    assert "'qwen9' could not be found or loaded" in str(info.value)


def test_server_error_is_retryable():
    def boom(request):
        return httpx.Response(500, json={"error": {"message": "oops"}})

    prov = build_local_provider(client_factory=HandlerFactory(boom), env={})
    with pytest.raises(LocalLLMError) as info:
        prov.resolve(system_prompt="s json", user_prompt="u")
    assert not info.value.fatal


def test_reply_that_only_thought_is_reported_as_thinking():
    def thought(request):
        reply = _chat_reply("")
        reply["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=reply)

    prov = build_local_provider(client_factory=HandlerFactory(thought), env={})
    with pytest.raises(LocalLLMError, match="without answering: it is thinking") as info:
        prov.resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal


# --- checked-in model profiles (ingredients.worker.local_profiles) ----------

_QWEN = LOCAL_MODEL_PROFILES["qwen3.5-9b"]


class FakeLMStudio:
    """Routes LM Studio's REST model API plus chat completions; ``loaded`` is
    the config of the loaded instance (None = not loaded)."""

    def __init__(
        self, loaded: dict | None = None, *, load_status: int = 200, downloaded: bool = True
    ) -> None:
        self.loaded = loaded
        self.downloaded = downloaded
        self.load_status = load_status
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/api/v1/models":
            instances = [] if self.loaded is None else [{"id": "qwen3.5-9b", "config": self.loaded}]
            models = [{"key": "qwen2.5-14b-instruct", "loaded_instances": []}]
            if self.downloaded:
                models.append({"key": "qwen3.5-9b", "loaded_instances": instances})
            return httpx.Response(200, json={"models": models})
        if path == "/api/v1/models/load":
            if self.load_status >= 400:
                return httpx.Response(self.load_status, json={"error": "out of memory"})
            self.loaded = {k: v for k, v in body.items() if k not in ("model", "ttl_seconds")}
            return httpx.Response(200, json={"instance_id": body["model"]})
        return httpx.Response(200, json=_chat_reply('{"results": []}'))

    def paths(self) -> list[str]:
        return [p for _, p, _ in self.calls]


def _qwen(server: FakeLMStudio, env: dict | None = None):
    return build_local_provider(
        client_factory=HandlerFactory(server), env=env or {}, model_id="qwen3.5-9b"
    )


def test_profiled_model_is_loaded_with_its_checked_in_settings():
    server = FakeLMStudio()
    _qwen(server).resolve(system_prompt="s json", user_prompt="u")

    assert server.paths() == ["/api/v1/models", "/api/v1/models/load", "/v1/chat/completions"]
    load = server.calls[1][2]
    assert load == {"model": "qwen3.5-9b", **_QWEN.load, "ttl_seconds": 300}


def test_profiled_model_already_loaded_with_its_settings_is_reused():
    server = FakeLMStudio(loaded={**_QWEN.load, "eval_batch_size": 2048})
    _qwen(server).resolve(system_prompt="s json", user_prompt="u")
    assert server.paths() == ["/api/v1/models", "/v1/chat/completions"]


def test_profiled_model_loaded_with_other_settings_fails_clearly():
    server = FakeLMStudio(loaded={**_QWEN.load, "context_length": 8192})
    with pytest.raises(LocalLLMError, match=r"context_length=8192 \(want 16384\)") as info:
        _qwen(server).resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal
    assert "/v1/chat/completions" not in server.paths()


def test_profile_load_failure_is_fatal():
    server = FakeLMStudio(load_status=500)
    with pytest.raises(LocalLLMError, match="could not be loaded with its checked-in profile") as info:
        _qwen(server).resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal


def test_profiled_model_not_downloaded_is_fatal():
    with pytest.raises(LocalLLMError, match="not downloaded") as info:
        _qwen(FakeLMStudio(downloaded=False)).resolve(system_prompt="s json", user_prompt="u")
    assert info.value.fatal


def test_profiled_model_sends_its_sampling_on_every_request():
    server = FakeLMStudio()
    _qwen(server).resolve(system_prompt="s json", user_prompt="u")
    chat = server.calls[-1][2]
    for key, value in _QWEN.sampling.items():
        assert chat[key] == value, key
    assert chat["reasoning_effort"] == "none"


def test_extra_body_overrides_the_profile():
    server = FakeLMStudio()
    _qwen(server, env={"LOCAL_LLM_EXTRA_BODY": '{"temperature": 0}'}).resolve(
        system_prompt="s json", user_prompt="u"
    )
    assert server.calls[-1][2]["temperature"] == 0


def test_unprofiled_model_skips_the_model_api():
    server = FakeLMStudio()
    build_local_provider(
        client_factory=HandlerFactory(server), env={}, model_id="qwen2.5-14b-instruct"
    ).resolve(system_prompt="s json", user_prompt="u")
    assert server.paths() == ["/v1/chat/completions"]
