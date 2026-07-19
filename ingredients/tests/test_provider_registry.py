"""The worker's provider registry: {provider_id -> impl} built from the env.

Ollama (local, free) is always registered; each hosted provider is registered
only when its API key is present, so a chain that names an unconfigured provider
fails loudly instead of silently doing nothing. No network: the SDK/httpx
clients construct offline.
"""

from __future__ import annotations

from common.llm.openai import OpenAIProvider
from ingredients.worker.providers_local import build_provider_impls


def test_ollama_always_registered_even_with_no_keys():
    """`ollama` is the one id for the local LLM tier (no `local`/`barbot`
    synonyms); it's always registered so the free tier needs no key."""
    impls = build_provider_impls(env={})
    assert set(impls) == {"ollama"}
    assert impls["ollama"].model_id == "qwen3:14b"


def test_registers_only_hosted_providers_with_credentials():
    env = {"OPENAI_API_KEY": "sk-o", "DEEPSEEK_API_KEY": "sk-d"}  # no ANTHROPIC key
    impls = build_provider_impls(env=env)

    assert set(impls) == {"ollama", "openai", "deepseek"}
    assert isinstance(impls["deepseek"], OpenAIProvider)
    assert impls["deepseek"].model_id == "deepseek-v4-flash"
    assert impls["openai"].model_id == "gpt-5.4-mini"


def test_all_providers_registered_when_all_keys_present():
    env = {
        "OPENAI_API_KEY": "sk-o",
        "ANTHROPIC_API_KEY": "sk-a",
        "DEEPSEEK_API_KEY": "sk-d",
    }
    impls = build_provider_impls(env=env)

    assert set(impls) == {"ollama", "openai", "claude", "deepseek"}
    assert impls["claude"].model_id == "claude-haiku-4-5"
