from unittest.mock import AsyncMock, patch

import pytest

from scraper.src.ollama_client import ClassificationResult, classify_url


@pytest.fixture
def fake_ollama_response():
    return {
        "message": {
            "role": "assistant",
            "content": '{"label": "likely_drink_recipe"}',
        },
        "done": True,
    }


async def test_classify_url_returns_parsed_label(fake_ollama_response):
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=fake_ollama_response)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        result = await classify_url(
            url="https://example.com/recipe/1",
            sitemap_source="recipes.xml",
            model="qwen3:14b",
        )

    assert isinstance(result, ClassificationResult)
    assert result.label == "likely_drink_recipe"
    assert result.raw_response == '{"label": "likely_drink_recipe"}'
    assert result.latency_ms >= 0


async def test_classify_url_sends_system_and_user_messages(fake_ollama_response):
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=fake_ollama_response)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        await classify_url("https://example.com/x", "s.xml", "qwen3:14b")

    call = mock_client.chat.await_args
    kwargs = call.kwargs
    assert kwargs["model"] == "qwen3:14b"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "https://example.com/x" in messages[1]["content"]
    assert kwargs["format"]["type"] == "object"


async def test_classify_url_raises_on_invalid_label():
    bad = {"message": {"content": '{"label": "not_a_real_label"}'}, "done": True}
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=bad)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="invalid label"):
            await classify_url("https://example.com/x", None, "qwen3:14b")


async def test_classify_url_raises_on_malformed_json():
    bad = {"message": {"content": "not json"}, "done": True}
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=bad)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="malformed"):
            await classify_url("https://example.com/x", None, "qwen3:14b")
