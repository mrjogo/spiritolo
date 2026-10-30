"""The free ``local`` LLM tier: a generic **OpenAI-compatible** server chosen by
URL (``LOCAL_LLM_BASE_URL``), LM Studio on barbot in practice.

The provider is the stock ``OpenAIProvider`` over ``<LOCAL_LLM_BASE_URL>/v1``;
``_LocalChatClient`` papers over the places a local runtime differs from
OpenAI's API (see its docstring), ``_ModelLoader`` applies a model's checked-in
load settings (``local_profiles``) through LM Studio's REST API, and transport
errors become a ``LocalLLMError`` that says what to check.

Barbot is only reachable over the tailnet, so when ``TS_LOCAL_PROXY`` is set
the local client routes through that SOCKS proxy. Hosted clients never do (see
``hosted_client_kwargs``): they are built with no proxy and ``trust_env=False``
so a global ``ALL_PROXY`` / ``HTTPS_PROXY`` can't pull them onto the tunnel.
The httpx client is built through an injectable ``client_factory`` so tests
exercise the split with a fake transport.

Used by the Zone-2 executor (``ingredients.worker.providers_local``) and by
``scraper.classify --provider local``.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from .local_profiles import LocalModelProfile, profile_for
from .openai import OpenAIProvider

log = logging.getLogger("common.llm.local")

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
DEFAULT_LOCAL_MODEL = "qwen3.5-9b"
# Idle unload for a model this client JIT-loads (see local_ttl_seconds).
DEFAULT_LOCAL_TTL_SECONDS = 300
# Thinking off by default (see local_reasoning_effort).
DEFAULT_LOCAL_REASONING_EFFORT = "none"
# Provider ids that select the local tier. `ollama` is the id runs assembled
# before the generic tier carry in `jobs.llm_provider`; it is an alias only.
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


def local_ttl_seconds(env: Env | None = None) -> int | None:
    """``LOCAL_LLM_TTL``: idle seconds before LM Studio unloads a model this
    client JIT-loaded, sent per request as ``ttl`` so spiritolo's setting never
    touches the server-wide default. Defaults to 300; an empty string omits it."""
    raw = _env(env).get("LOCAL_LLM_TTL", str(DEFAULT_LOCAL_TTL_SECONDS))
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"LOCAL_LLM_TTL must be a number of seconds, got {raw!r}") from exc


class LocalLLMError(Exception):
    """A local-tier failure with a message that says what to check.

    ``fatal`` errors (server not running, model can't load, the model spends its
    whole budget thinking) fail the run at once with this message instead of
    being retried pack after pack; ``status_code`` keeps an HTTP error's code."""

    def __init__(self, message: str, *, fatal: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.fatal = fatal
        self.status_code = status_code


_RUNBOOK = "see docs/pipeline.md#local-llm-tier-lm-studio-on-barbot"


def _translate_error(exc: Exception, base_url: str, model: str) -> Exception:
    import openai

    if isinstance(exc, openai.APITimeoutError):
        return LocalLLMError(
            f"local LLM server at {base_url} timed out (model {model!r} may still be "
            "loading, or the GPU is busy); retrying", fatal=False,
        )
    if isinstance(exc, openai.APIConnectionError):
        return LocalLLMError(
            f"local LLM server not reachable at {base_url}: is LM Studio running "
            f"and reachable over the tailnet? ({_RUNBOOK}; underlying error: "
            f"{exc.__cause__ or exc})", fatal=True,
        )
    if isinstance(exc, openai.APIStatusError):
        code = exc.status_code
        hint = (
            f"model {model!r} could not be found or loaded: is it downloaded, and "
            "does it fit in VRAM next to whatever else is loaded?"
            if code in (400, 404) else "the local server rejected the request"
        )
        return LocalLLMError(
            f"local LLM server at {base_url} returned {code}: {hint} ({exc.message})",
            fatal=code < 500, status_code=code,
        )
    return exc


def _check_answered(resp: Any, model: str) -> None:
    """A reply cut off with no content at all means the model reasoned through the
    whole token budget, not that it wrote bad JSON."""
    choice = (getattr(resp, "choices", None) or [None])[0]
    if choice is None:
        return
    content = getattr(choice.message, "content", None)
    if not content and getattr(choice, "finish_reason", None) == "length":
        raise LocalLLMError(
            f"local model {model!r} used its whole token budget without answering: "
            "it is thinking. Set LOCAL_LLM_REASONING_EFFORT=none (the default) or "
            f"turn thinking off for the model ({_RUNBOOK})", fatal=True,
        )


def _model_key(entry: dict[str, Any]) -> str | None:
    for k in ("key", "id", "model_key", "modelKey"):
        if isinstance(entry.get(k), str):
            return entry[k]
    return None


class _ModelLoader:
    """Makes sure a profiled model is loaded with its checked-in load settings
    (``local_profiles``) before each request, over LM Studio's REST API.

    Not loaded → ``POST /api/v1/models/load`` with the profile. Loaded with the
    profile's settings → nothing to do. Loaded with other settings (someone
    loaded it by hand, or with the server's defaults) → a fatal error naming the
    difference: LM Studio has no HTTP unload, and running on settings nobody
    chose is what the profile exists to prevent. Checked before every request
    because the idle TTL can unload the model between packs, and a JIT reload
    would come back on the server's defaults."""

    def __init__(
        self, http: Any, base_url: str, profile: LocalModelProfile, ttl: int | None
    ) -> None:
        self._http = http
        self._base_url = base_url
        self._profile = profile
        self._ttl = ttl

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self._http.request(method, self._base_url + path, **kwargs)
        except httpx.TimeoutException as exc:
            raise LocalLLMError(
                f"local LLM server at {self._base_url} timed out on {path}; retrying",
                fatal=False,
            ) from exc
        except httpx.TransportError as exc:
            raise LocalLLMError(
                f"local LLM server not reachable at {self._base_url}: is LM Studio running "
                f"and reachable over the tailnet? ({_RUNBOOK}; underlying error: {exc})",
                fatal=True,
            ) from exc

    def ensure(self, model: str) -> None:
        resp = self._call("GET", "/api/v1/models")
        if resp.status_code >= 400:
            raise LocalLLMError(
                f"{self._base_url} has no LM Studio model API (GET /api/v1/models "
                f"returned {resp.status_code}), so {model!r}'s checked-in load "
                "settings cannot be applied", fatal=True, status_code=resp.status_code,
            )
        body = resp.json()
        entries = body.get("models", body.get("data", [])) if isinstance(body, dict) else body
        entry = next((m for m in entries or [] if _model_key(m) == model), None)
        if entry is None:
            raise LocalLLMError(
                f"model {model!r} is not downloaded on {self._base_url} ({_RUNBOOK})",
                fatal=True,
            )
        wanted = self._profile.load
        instances = entry.get("loaded_instances") or []
        diffs = []
        for inst in instances:
            config = inst.get("config") or {}
            diff = {k: config.get(k) for k, v in wanted.items() if config.get(k) != v}
            if not diff:
                return
            diffs.append(diff)
        if diffs:
            got = ", ".join(f"{k}={v!r} (want {wanted[k]!r})" for k, v in diffs[0].items())
            raise LocalLLMError(
                f"model {model!r} is already loaded on {self._base_url} with settings "
                f"that differ from its checked-in profile: {got}. Unload it "
                f"(lms unload {model}) and retry the run", fatal=True,
            )
        load = {"model": model, **wanted}
        if self._ttl is not None:
            load["ttl_seconds"] = self._ttl
        resp = self._call("POST", "/api/v1/models/load", json=load)
        if resp.status_code >= 400:
            raise LocalLLMError(
                f"model {model!r} could not be loaded with its checked-in profile "
                f"(returned {resp.status_code}: {resp.text[:300]}): does it fit in VRAM "
                "next to whatever else is loaded?", fatal=True, status_code=resp.status_code,
            )


class _Completions:
    def __init__(
        self,
        inner: Any,
        extra_body: dict[str, Any],
        reasoning_effort: str | None = None,
        base_url: str = "",
        loader: _ModelLoader | None = None,
    ) -> None:
        self._inner = inner
        self._extra_body = extra_body
        self._reasoning_effort = reasoning_effort
        self._base_url = base_url
        self._loader = loader

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
        model = kwargs.get("model", "")
        if self._loader is not None:
            self._loader.ensure(model)
        try:
            resp = self._inner.create(**kwargs)
        except Exception as exc:
            translated = _translate_error(exc, self._base_url, model)
            if translated is exc:
                raise
            raise translated from exc
        _check_answered(resp, model)
        return resp


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
    - ``ttl`` (``LOCAL_LLM_TTL``, default 300 s) and ``LOCAL_LLM_EXTRA_BODY``
      are merged in as ``extra_body``.
    - Transport and HTTP errors become a ``LocalLLMError`` that names what to
      check (server down, model not loadable), and a reply that spent the whole
      budget thinking is reported as such rather than as malformed JSON.
    """

    def __init__(
        self,
        inner: Any,
        extra_body: dict[str, Any],
        reasoning_effort: str | None = None,
        base_url: str = "",
        loader: _ModelLoader | None = None,
    ) -> None:
        self._inner = inner
        self.chat = _Chat(
            _Completions(inner.chat.completions, extra_body, reasoning_effort, base_url, loader)
        )

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
    a falsy value falls back to ``LOCAL_LLM_MODEL``, then ``DEFAULT_LOCAL_MODEL``.

    A model with a checked-in profile (``local_profiles``) is loaded with the
    profile's settings and sent its sampling on every request, so nothing
    depends on the server's defaults; ``LOCAL_LLM_EXTRA_BODY`` still wins."""
    import openai

    e = _env(env)
    model = model_id or e.get("LOCAL_LLM_MODEL") or DEFAULT_LOCAL_MODEL
    profile = profile_for(model)
    ttl = local_ttl_seconds(e)
    extra_body: dict[str, Any] = {}
    if ttl is not None:
        extra_body["ttl"] = ttl
    if profile is not None:
        extra_body.update(profile.sampling)
    else:
        log.warning("local model %r has no checked-in profile; using the server's defaults", model)
    extra_body.update(local_extra_body(e))
    base_url = local_base_url(e)
    factory = httpx.Client if client_factory is None else client_factory
    http = factory(**local_client_kwargs(e))
    loader = (
        _ModelLoader(http, base_url, profile, ttl)
        if profile is not None and profile.load
        else None
    )
    sdk = openai.OpenAI(
        # Neither runtime checks the key, but the SDK requires one.
        api_key=e.get("LOCAL_LLM_API_KEY") or "local",
        base_url=base_url + "/v1",
        http_client=http,
        # The chain retries a pack itself; an SDK retry would re-send a long
        # local generation that timed out.
        max_retries=0,
    )
    provider = OpenAIProvider(
        client=_LocalChatClient(sdk, extra_body, local_reasoning_effort(e), base_url, loader),
        model_id=model,
    )
    provider.cost_per_call = 0  # type: ignore[attr-defined]  # local is unmetered
    return provider
