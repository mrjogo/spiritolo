"""Provider HTTP clients with an explicit local-vs-hosted proxy split.

The worker runs in a Railway container that joins the tailnet through Tailscale
in userspace-networking mode, exposing a local SOCKS proxy. Barbot's Ollama (the
free ``local`` provider) is only reachable over that tailnet, so its client
routes through the proxy named in ``TS_LOCAL_PROXY``. Every hosted API
(OpenAI / Claude / ScraperAPI) is reachable on the direct route and must NOT
tunnel through barbot's uplink — so their clients are built with no proxy and
with ``trust_env=False``, which severs any global ``ALL_PROXY`` / ``HTTPS_PROXY``
so an env var can't silently pull them onto the tunnel.

Proxying is therefore always explicit: the local client is the only one that
ever carries a ``proxy`` kwarg, and only when ``TS_LOCAL_PROXY`` is set. The
httpx client is built through an injectable ``client_factory`` so tests exercise
the split with a fake transport.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from common.llm.claude import ClaudeProvider
from common.llm.deepseek import build_deepseek_provider
from common.llm.ollama import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, OllamaProvider
from common.llm.openai import OpenAIProvider

Env = Mapping[str, str]
ClientFactory = Callable[..., Any]


def _env(env: Env | None) -> Env:
    return os.environ if env is None else env


def local_client_kwargs(env: Env | None = None) -> dict[str, Any]:
    """httpx kwargs for the local (Ollama) client: direct env-proxy inheritance
    is severed, and a ``proxy`` is added only when ``TS_LOCAL_PROXY`` is set."""
    kwargs: dict[str, Any] = {"timeout": DEFAULT_TIMEOUT, "trust_env": False}
    proxy = _env(env).get("TS_LOCAL_PROXY")
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def hosted_client_kwargs(env: Env | None = None) -> dict[str, Any]:  # noqa: ARG001
    """httpx kwargs for a hosted client: the direct route, always. No proxy, and
    ``trust_env=False`` so a global ALL_PROXY / HTTPS_PROXY can't tunnel it."""
    return {"timeout": DEFAULT_TIMEOUT, "trust_env": False}


def build_local_ollama_provider(
    *, client_factory: ClientFactory | None = None, env: Env | None = None
) -> OllamaProvider:
    """Build the local Ollama provider whose client tunnels through the tailnet
    proxy (``TS_LOCAL_PROXY``); base URL from ``OLLAMA_BASE_URL``."""
    factory = httpx.Client if client_factory is None else client_factory
    base_url = _env(env).get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
    client = factory(**local_client_kwargs(env))
    return OllamaProvider(client=client, base_url=base_url)


def build_openai_http_client(
    *, client_factory: ClientFactory | None = None, env: Env | None = None
) -> Any:
    """Direct-route httpx client for the OpenAI SDK (``http_client=``)."""
    factory = httpx.Client if client_factory is None else client_factory
    return factory(**hosted_client_kwargs(env))


def build_claude_http_client(
    *, client_factory: ClientFactory | None = None, env: Env | None = None
) -> Any:
    """Direct-route httpx client for the Anthropic SDK (``http_client=``)."""
    factory = httpx.Client if client_factory is None else client_factory
    return factory(**hosted_client_kwargs(env))


def build_scraperapi_http_client(
    *, client_factory: ClientFactory | None = None, env: Env | None = None
) -> Any:
    """Direct-route httpx client for ScraperAPI fetch calls."""
    factory = httpx.Client if client_factory is None else client_factory
    return factory(**hosted_client_kwargs(env))


def build_provider_impls(
    *, env: Env | None = None, client_factory: ClientFactory | None = None
) -> dict[str, Any]:
    """The worker's ``{provider_id -> impl}`` registry, built from the env.

    The local Ollama tier (free) is always registered under every zero-cost
    local id the cost table names — ``ollama`` / ``local`` / ``barbot`` — all
    pointing at the same client, so a chain config may reference any of them.
    Each hosted provider — ``openai`` / ``claude`` / ``deepseek`` — is registered
    only when its API key is present in ``env``; an absent key means an absent
    id, so a ``PROVIDER_CHAIN_CONFIG`` that names an unconfigured provider fails
    loudly (``KeyError`` in the chain) rather than silently skipping the tier.
    Hosted clients take the direct route; only the local Ollama client tunnels
    the tailnet proxy (see module docstring).
    """
    e = _env(env)
    ollama = build_local_ollama_provider(client_factory=client_factory, env=env)
    impls: dict[str, Any] = {"ollama": ollama, "local": ollama, "barbot": ollama}
    if e.get("OPENAI_API_KEY"):
        impls["openai"] = OpenAIProvider.from_env(
            api_key=e["OPENAI_API_KEY"],
            http_client=build_openai_http_client(client_factory=client_factory, env=env),
        )
    if e.get("ANTHROPIC_API_KEY"):
        impls["claude"] = ClaudeProvider.from_env(
            api_key=e["ANTHROPIC_API_KEY"],
            http_client=build_claude_http_client(client_factory=client_factory, env=env),
        )
    if e.get("DEEPSEEK_API_KEY"):
        # DeepSeek is OpenAI-compatible, so it takes the same direct-route client.
        impls["deepseek"] = build_deepseek_provider(
            api_key=e["DEEPSEEK_API_KEY"],
            http_client=build_openai_http_client(client_factory=client_factory, env=env),
        )
    return impls
