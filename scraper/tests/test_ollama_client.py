from unittest.mock import MagicMock

import pytest

from common.llm.provider import ProviderResult
from scraper.ollama_client import ClassificationResult, classify_url


def _stub_provider(reply: str) -> MagicMock:
    p = MagicMock()
    p.resolve.return_value = ProviderResult(raw_text=reply, model_id="qwen3:14b")
    return p


def test_classify_url_returns_label():
    provider = _stub_provider('{"label": "likely_drink_recipe"}')
    out = classify_url(
        url="https://example.com/recipes/margarita",
        sitemap_source=None, provider=provider,
    )
    assert isinstance(out, ClassificationResult)
    assert out.label == "likely_drink_recipe"
    assert out.raw_response == '{"label": "likely_drink_recipe"}'
    assert out.latency_ms >= 0
    provider.resolve.assert_called_once()


def test_classify_url_raises_on_malformed_json():
    provider = _stub_provider("not json")
    with pytest.raises(ValueError, match="malformed JSON"):
        classify_url(url="https://x", sitemap_source=None, provider=provider)


def test_classify_url_raises_on_unknown_label():
    provider = _stub_provider('{"label": "nonsense"}')
    with pytest.raises(ValueError, match="invalid label"):
        classify_url(url="https://x", sitemap_source=None, provider=provider)


def test_classify_url_passes_system_and_user_prompts():
    provider = _stub_provider('{"label": "likely_drink_recipe"}')
    classify_url(
        url="https://example.com/x",
        sitemap_source="recipes.xml",
        provider=provider,
    )
    kwargs = provider.resolve.call_args.kwargs
    assert "system_prompt" in kwargs
    assert "user_prompt" in kwargs
    assert "https://example.com/x" in kwargs["user_prompt"]
    assert "recipes.xml" in kwargs["user_prompt"]
