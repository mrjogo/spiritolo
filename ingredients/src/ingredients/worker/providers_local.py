"""Provider HTTP clients with an explicit local-vs-hosted proxy split.

The worker runs in a Railway container that joins the tailnet through Tailscale
in userspace-networking mode, exposing a local SOCKS proxy. Barbot's local LLM
server (LM Studio, or Ollama — the free ``local`` provider) is only reachable
over that tailnet, so its client routes through the proxy named in
``TS_LOCAL_PROXY``. Every hosted API (OpenAI / Claude / ScraperAPI) is reachable
on the direct route and must NOT tunnel through barbot's uplink — so their
clients are built with no proxy and with ``trust_env=False``, which severs any
global ``ALL_PROXY`` / ``HTTPS_PROXY`` so an env var can't silently pull them
onto the tunnel.

Proxying is therefore always explicit: the local client is the only one that
ever carries a ``proxy`` kwarg, and only when ``TS_LOCAL_PROXY`` is set. The
httpx client is built through an injectable ``client_factory`` so tests exercise
the split with a fake transport.

The local tier is a generic **OpenAI-compatible** endpoint chosen by URL
(``LOCAL_LLM_BASE_URL``): both LM Studio and Ollama serve
``/v1/chat/completions``, so the provider is an ``OpenAIProvider`` and the code
knows nothing about which runtime answers. ``_LocalChatClient`` papers over the
two places a local runtime differs from OpenAI's API (see its docstring).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from common.llm.claude import ClaudeProvider
from common.llm.deepseek import build_deepseek_provider
from common.llm.openai import OpenAIProvider

Env = Mapping[str, str]
ClientFactory = Callable[..., Any]

DEFAULT_TIMEOUT = 120.0
# A local model may be JIT-loaded into VRAM on its first request (LM Studio does
# this when a run names a model that isn't loaded), so its client gets a far
# longer budget than a hosted call.
LOCAL_TIMEOUT = 600.0
# LM Studio's default server port. Ollama is http://<host>:11434.
DEFAULT_LOCAL_BASE_URL = "http://localhost:1234"
# Used when neither the run nor LOCAL_LLM_MODEL names a model.
DEFAULT_LOCAL_MODEL = "qwen3:14b"
# Thinking off by default (see local_reasoning_effort).
DEFAULT_LOCAL_REASONING_EFFORT = "none"
# Provider ids that select the local tier. `ollama` is what runs assembled
# before the generic tier carry in `jobs.llm_provider`.
LOCAL_PROVIDER_IDS = ("local", "ollama")

# `response_format={"type": "json_object"}` (the OpenAI path's schema-less JSON
# mode) has no LM Studio equivalent — it accepts only `json_schema` / `text`. A
# schema for "any object" keeps the JSON constraint on every local runtime.
_ANY_OBJECT_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "answer", "schema": {"type": "object"}},
}


def _env(env: Env | None) -> Env:
    return os.environ if env is None else env


def local_client_kwargs(env: Env | None = None) -> dict[str, Any]:
    """httpx kwargs for the local client: direct env-proxy inheritance is
    severed, and a ``proxy`` is added only when ``TS_LOCAL_PROXY`` is set."""
    kwargs: dict[str, Any] = {"timeout": LOCAL_TIMEOUT, "trust_env": False}
    proxy = _env(env).get("TS_LOCAL_PROXY")
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def hosted_client_kwargs(env: Env | None = None) -> dict[str, Any]:  # noqa: ARG001
    """httpx kwargs for a hosted client: the direct route, always. No proxy, and
    ``trust_env=False`` so a global ALL_PROXY / HTTPS_PROXY can't tunnel it."""
    return {"timeout": DEFAULT_TIMEOUT, "trust_env": False}


def local_base_url(env: Env | None = None) -> str:
    """The local server's root URL, without ``/v1``. ``LOCAL_LLM_BASE_URL`` wins;
    ``OLLAMA_BASE_URL`` is still read for one release so an existing deploy keeps
    working; else LM Studio's localhost default."""
    e = _env(env)
    base = e.get("LOCAL_LLM_BASE_URL") or e.get("OLLAMA_BASE_URL") or DEFAULT_LOCAL_BASE_URL
    return base.rstrip("/").removesuffix("/v1")


def local_extra_body(env: Env | None = None) -> dict[str, Any]:
    """``LOCAL_LLM_EXTRA_BODY``: a JSON object merged into every local request
    (runtime-specific knobs such as a chat-template flag that turns a model's
    thinking off). Unset → ``{}``; anything but a JSON object is a config error."""
    raw = _env(env).get("LOCAL_LLM_EXTRA_BODY")
    if not raw:
        return {}
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LOCAL_LLM_EXTRA_BODY is not valid JSON: {exc}") from exc
    if not isinstance(extra, dict):
        raise ValueError("LOCAL_LLM_EXTRA_BODY must be a JSON object")  # noqa: TRY004
    return extra


def local_reasoning_effort(env: Env | None = None) -> str | None:
    """``LOCAL_LLM_REASONING_EFFORT``, sent as ``reasoning_effort`` on every local
    request. Defaults to ``none``: LM Studio honours it for Qwen3.5 (zero
    reasoning tokens) where it ignores ``chat_template_kwargs.enable_thinking``,
    and a thinking model otherwise spends the whole token budget reasoning and
    returns empty content. Set it to an empty string to omit the field for a
    runtime that rejects it."""
    value = _env(env).get("LOCAL_LLM_REASONING_EFFORT", DEFAULT_LOCAL_REASONING_EFFORT)
    return value or None


class _Completions:
    def __init__(
        self, inner: Any, extra_body: dict[str, Any], reasoning_effort: str | None = None
    ) -> None:
        self._inner = inner
        self._extra_body = extra_body
        self._reasoning_effort = reasoning_effort

    def create(self, **kwargs: Any) -> Any:
        fmt = kwargs.get("response_format")
        if isinstance(fmt, dict) and fmt.get("type") == "json_object":
            kwargs["response_format"] = _ANY_OBJECT_FORMAT
        if "max_completion_tokens" in kwargs and "max_tokens" not in kwargs:
            kwargs["max_tokens"] = kwargs["max_completion_tokens"]
        if self._reasoning_effort and "reasoning_effort" not in kwargs:
            kwargs["reasoning_effort"] = self._reasoning_effort
        if self._extra_body:
            kwargs["extra_body"] = {**self._extra_body, **(kwargs.get("extra_body") or {})}
        return self._inner.create(**kwargs)


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _LocalChatClient:
    """An ``openai.OpenAI`` client as a local runtime needs it.

    ``OpenAIProvider`` only ever calls ``client.chat.completions.create``; this
    wraps that one call so the provider stays the stock OpenAI one:

    - ``response_format`` ``json_object`` → a ``json_schema`` for any object
      (LM Studio rejects ``json_object``); a real ``json_schema`` passes through.
    - ``max_completion_tokens`` is mirrored to ``max_tokens``, which older
      OpenAI-compatible servers read instead.
    - ``reasoning_effort`` (``LOCAL_LLM_REASONING_EFFORT``, default ``none``) is
      added unless the caller set one, so a thinking model answers directly.
    - ``LOCAL_LLM_EXTRA_BODY`` is merged in as ``extra_body``.
    """

    def __init__(
        self, inner: Any, extra_body: dict[str, Any], reasoning_effort: str | None = None
    ) -> None:
        self._inner = inner
        self.chat = _Chat(_Completions(inner.chat.completions, extra_body, reasoning_effort))

    @property
    def base_url(self) -> Any:
        return self._inner.base_url


def build_local_provider(
    *,
    client_factory: ClientFactory | None = None,
    env: Env | None = None,
    model_id: str | None = None,
) -> OpenAIProvider:
    """Build the local provider: an ``OpenAIProvider`` over
    ``<LOCAL_LLM_BASE_URL>/v1`` whose client tunnels through the tailnet proxy
    (``TS_LOCAL_PROXY``). Free, so ``cost_per_call`` is 0.

    ``model_id`` (the run's ``jobs.llm_model``) selects the model, in the
    runtime's own naming (LM Studio ``qwen/qwen3-14b``, Ollama ``qwen3:14b``);
    a falsy value falls back to ``LOCAL_LLM_MODEL``, then ``DEFAULT_LOCAL_MODEL``."""
    import openai

    e = _env(env)
    extra_body = local_extra_body(e)
    factory = httpx.Client if client_factory is None else client_factory
    sdk = openai.OpenAI(
        # Neither runtime checks the key, but the SDK requires one.
        api_key=e.get("LOCAL_LLM_API_KEY") or "local",
        base_url=local_base_url(e) + "/v1",
        http_client=factory(**local_client_kwargs(e)),
        # The chain retries a pack itself; an SDK retry would re-send a long
        # local generation that timed out.
        max_retries=0,
    )
    provider = OpenAIProvider(
        client=_LocalChatClient(sdk, extra_body, local_reasoning_effort(e)),
        model_id=model_id or e.get("LOCAL_LLM_MODEL") or DEFAULT_LOCAL_MODEL,
    )
    provider.cost_per_call = 0  # type: ignore[attr-defined]  # local is unmetered
    return provider


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
