"""The worker builds a run's single LLM provider from its chosen tier.

A run carries ``jobs.llm_provider`` + ``jobs.llm_model``; the worker turns that
into exactly one provider impl via ``build_provider_for_run``, threading the
run's model into construction (falling back to the provider's DEFAULT when the
run named none). Ollama (local, free) is always available; each hosted provider
is built only when its API key is present, else ``None`` — a run with no provider
or no key runs deterministic-only. No network: the SDK/httpx clients construct
offline.
"""

from __future__ import annotations

from common.llm.claude import ClaudeProvider
from common.llm.openai import OpenAIProvider
from ingredients.worker.providers_local import (
    available_providers,
    build_provider_for_run,
)


def test_ollama_always_available_even_with_no_keys():
    # `ollama` is the one id for the local LLM tier; always available, no key.
    prov = build_provider_for_run("ollama", None, env={})
    assert prov is not None
    assert prov.model_id == "qwen3:14b"  # DEFAULT when the run named no model


def test_ollama_threads_the_runs_model():
    prov = build_provider_for_run("ollama", "llama3:70b", env={})
    assert prov.model_id == "llama3:70b"


def test_openai_uses_the_runs_model():
    prov = build_provider_for_run(
        "openai", "gpt-5-mini", env={"OPENAI_API_KEY": "sk-o"}
    )
    assert isinstance(prov, OpenAIProvider)
    assert prov.model_id == "gpt-5-mini"


def test_openai_falls_back_to_default_model():
    prov = build_provider_for_run("openai", None, env={"OPENAI_API_KEY": "sk-o"})
    assert prov is not None
    assert prov.model_id == "gpt-5.4-mini"  # DEFAULT


def test_openai_without_key_is_none():
    assert build_provider_for_run("openai", "gpt-5-mini", env={}) is None


def test_anthropic_uses_the_runs_model():
    prov = build_provider_for_run(
        "anthropic", "claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "sk-a"}
    )
    assert isinstance(prov, ClaudeProvider)
    assert prov.model_id == "claude-sonnet-4-5"


def test_anthropic_falls_back_to_default_model():
    prov = build_provider_for_run("anthropic", None, env={"ANTHROPIC_API_KEY": "sk-a"})
    assert prov.model_id == "claude-haiku-4-5"  # DEFAULT


def test_available_providers_lists_anthropic_when_key_present():
    assert "anthropic" in available_providers({"ANTHROPIC_API_KEY": "k"})


def test_deepseek_builds_an_openai_compatible_provider():
    prov = build_provider_for_run("deepseek", None, env={"DEEPSEEK_API_KEY": "sk-d"})
    assert isinstance(prov, OpenAIProvider)
    assert prov.model_id == "deepseek-v4-flash"  # DEFAULT


def test_deepseek_without_key_is_none():
    assert build_provider_for_run("deepseek", None, env={}) is None


def test_unknown_or_missing_provider_is_none():
    assert build_provider_for_run("mistral", "big", env={"MISTRAL_API_KEY": "x"}) is None
    assert build_provider_for_run(None, None, env={}) is None
