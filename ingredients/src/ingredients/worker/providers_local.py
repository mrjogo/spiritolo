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
    *,
    client_factory: ClientFactory | None = None,
    env: Env | None = None,
    model_id: str | None = None,
) -> OllamaProvider:
    """Build the local Ollama provider whose client tunnels through the tailnet
    proxy (``TS_LOCAL_PROXY``); base URL from ``OLLAMA_BASE_URL``.

    ``model_id`` (the run's ``jobs.llm_model``) selects the model; a falsy value
    falls back to ``OllamaProvider``'s DEFAULT model."""
    factory = httpx.Client if client_factory is None else client_factory
    base_url = _env(env).get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
    client = factory(**local_client_kwargs(env))
    model_kwargs = {"model_id": model_id} if model_id else {}
    return OllamaProvider(client=client, base_url=base_url, **model_kwargs)


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


def available_providers(env: Env | None = None) -> list[str]:
    """Which LLM providers this worker can actually service, given the API keys
    in ``env``. ``ollama`` (local, free) is always available; each hosted
    provider appears only when its key is present. The worker publishes this to
    ``worker_status`` so /ops can warn before a run is assembled for a provider
    the worker has no key for (the run-#7 DeepSeek footgun)."""
    e = _env(env)
    out = ["ollama"]
    if e.get("OPENAI_API_KEY"):
        out.append("openai")
    if e.get("ANTHROPIC_API_KEY"):
        out.append("claude")
    if e.get("DEEPSEEK_API_KEY"):
        out.append("deepseek")
    return out


def build_provider_for_run(
    provider_id: str | None,
    model_id: str | None = None,
    *,
    env: Env | None = None,
    client_factory: ClientFactory | None = None,
) -> Any | None:
    """Build the single LLM provider a run selected, or ``None``.

    A run carries its LLM tier on the job row: ``jobs.llm_provider`` (chosen at
    run assembly, read here as ``provider_id``) and ``jobs.llm_model`` (read as
    ``model_id``). This constructs exactly that one provider impl, threading
    ``model_id`` into its construction; a falsy ``model_id`` falls back to the
    provider's DEFAULT model.

    ``ollama`` (local, free) is always available — the one id for the local LLM,
    no ``local`` / ``barbot`` synonyms — and its client tunnels the tailnet proxy
    (see module docstring). Each hosted provider — ``openai`` / ``claude`` /
    ``deepseek`` — is returned only when its API key is present in ``env``; an
    absent key (or an unknown / ``None`` ``provider_id``) yields ``None``, and the
    run then runs deterministic-only (no LLM tier). Hosted clients take the direct
    route.
    """
    e = _env(env)
    if provider_id == "ollama":
        return build_local_ollama_provider(
            client_factory=client_factory, env=env, model_id=model_id
        )
    model_kwargs = {"model_id": model_id} if model_id else {}
    if provider_id == "openai" and e.get("OPENAI_API_KEY"):
        return OpenAIProvider.from_env(
            api_key=e["OPENAI_API_KEY"],
            http_client=build_openai_http_client(client_factory=client_factory, env=env),
            **model_kwargs,
        )
    if provider_id == "claude" and e.get("ANTHROPIC_API_KEY"):
        return ClaudeProvider.from_env(
            api_key=e["ANTHROPIC_API_KEY"],
            http_client=build_claude_http_client(client_factory=client_factory, env=env),
            **model_kwargs,
        )
    if provider_id == "deepseek" and e.get("DEEPSEEK_API_KEY"):
        # DeepSeek is OpenAI-compatible, so it takes the same direct-route client.
        return build_deepseek_provider(
            api_key=e["DEEPSEEK_API_KEY"],
            http_client=build_openai_http_client(client_factory=client_factory, env=env),
            **model_kwargs,
        )
    return None
