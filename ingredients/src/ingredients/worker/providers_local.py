"""Build the one LLM provider a run selected.

The local tier (barbot's LM Studio over the tailnet) lives in
``common.llm.local``; this module adds the hosted providers' direct-route
clients and the per-run factory. The proxy split: only the local client ever
carries a ``proxy`` (``TS_LOCAL_PROXY``), hosted clients take the direct route
with ``trust_env=False``. See ``common.llm.local`` for the details.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from common.llm.claude import ClaudeProvider
from common.llm.deepseek import build_deepseek_provider
from common.llm.local import (  # noqa: F401  (re-exported for the executor + tests)
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    LOCAL_PROVIDER_IDS,
    LocalLLMError,
    build_local_provider,
    hosted_client_kwargs,
    local_base_url,
    local_client_kwargs,
    local_extra_body,
    local_reasoning_effort,
    local_ttl_seconds,
)
from common.llm.openai import OpenAIProvider

Env = Mapping[str, str]
ClientFactory = Callable[..., Any]


def _env(env: Env | None) -> Env:
    import os
    return os.environ if env is None else env


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


def available_providers(env: Env | None = None) -> list[str]:
    """Which LLM providers this worker can actually service, given the API keys
    in ``env``. ``local`` (free) is always available; each hosted
    provider appears only when its key is present. The worker publishes this to
    ``worker_status`` so /ops can warn before a run is assembled for a provider
    the worker has no key for (the run-#7 DeepSeek footgun)."""
    e = _env(env)
    out = ["local"]
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

    ``local`` (free) is always available — ``ollama`` is accepted as an alias, the
    id runs assembled before the generic local tier carry — and its client
    tunnels the tailnet proxy (see module docstring). Each hosted provider — ``openai`` / ``claude`` /
    ``deepseek`` — is returned only when its API key is present in ``env``; an
    absent key (or an unknown / ``None`` ``provider_id``) yields ``None``, and the
    run then runs deterministic-only (no LLM tier). Hosted clients take the direct
    route.
    """
    e = _env(env)
    if provider_id in LOCAL_PROVIDER_IDS:
        return build_local_provider(
            client_factory=client_factory, env=env, model_id=model_id
        )
    model_kwargs = {"model_id": model_id} if model_id else {}
    if provider_id == "openai" and e.get("OPENAI_API_KEY"):
        return OpenAIProvider.from_env(
            api_key=e["OPENAI_API_KEY"],
            http_client=build_openai_http_client(client_factory=client_factory, env=env),
            **model_kwargs,
        )
    if provider_id in ("claude", "anthropic") and e.get("ANTHROPIC_API_KEY"):
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
