"""The local-vs-hosted provider proxy split.

The worker reaches barbot's Ollama over a Tailscale userspace SOCKS proxy, but
hosted APIs (OpenAI / Claude / ScraperAPI) must take the direct route — their
traffic must not tunnel through barbot's uplink. So only the local client reads
``TS_LOCAL_PROXY``; the hosted clients are constructed with no proxy and with
env-proxy inheritance severed (``trust_env=False``), so a global ``ALL_PROXY`` /
``HTTPS_PROXY`` can't leak them onto the tunnel.

Pure test: the httpx client is built through an injected factory that records
its kwargs — no real transport, no network.
"""
from __future__ import annotations

from ingredients.worker.providers_local import (
    build_claude_http_client,
    build_local_ollama_provider,
    build_openai_http_client,
)

_HOSTED = (build_openai_http_client, build_claude_http_client)


class RecordingFactory:
    """Stand-in for ``httpx.Client`` that captures the kwargs it was built with."""

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return object()


def test_local_client_uses_ts_proxy():
    env = {
        "TS_LOCAL_PROXY": "socks5://localhost:1055",
        "OLLAMA_BASE_URL": "http://barbot:11434",
    }
    fac = RecordingFactory()
    provider = build_local_ollama_provider(client_factory=fac, env=env)

    assert fac.kwargs["proxy"] == "socks5://localhost:1055"
    assert provider.base_url == "http://barbot:11434"


def test_hosted_clients_bypass_proxy():
    # TS_LOCAL_PROXY is present, but a hosted client must never read it.
    env = {"TS_LOCAL_PROXY": "socks5://localhost:1055"}
    for build in _HOSTED:
        fac = RecordingFactory()
        build(client_factory=fac, env=env)
        assert "proxy" not in fac.kwargs, f"{build.__name__} tunneled through the proxy"


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
    build_local_ollama_provider(client_factory=fac, env=env)
    assert "proxy" not in fac.kwargs
    assert fac.kwargs.get("trust_env") is False
