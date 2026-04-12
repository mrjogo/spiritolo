import os

import responses

from scraper.src.client import ScraperAPIClient, ScraperAPIError


@responses.activate
def test_fetch_returns_html():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="<html><body>Hello</body></html>",
        status=200,
    )
    client = ScraperAPIClient(api_key="test-key")
    html = client.fetch("https://example.com/recipe/1")
    assert "<body>Hello</body>" in html
    assert responses.calls[0].request.params["api_key"] == "test-key"
    assert responses.calls[0].request.params["url"] == "https://example.com/recipe/1"


@responses.activate
def test_fetch_raises_on_500():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="Internal Server Error",
        status=500,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised ScraperAPIError"
    except ScraperAPIError as e:
        assert "500" in str(e)


@responses.activate
def test_fetch_raises_on_403():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="Forbidden",
        status=403,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised ScraperAPIError"
    except ScraperAPIError as e:
        assert "403" in str(e)


@responses.activate
def test_fetch_passes_render_param():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="<html>rendered</html>",
        status=200,
    )
    client = ScraperAPIClient(api_key="test-key")
    client.fetch("https://example.com/recipe/1", render=True)
    assert responses.calls[0].request.params["render"] == "true"


def test_client_reads_api_key_from_env(monkeypatch):
    monkeypatch.setenv("SCRAPERAPI_KEY", "env-key")
    client = ScraperAPIClient()
    assert client.api_key == "env-key"


def test_client_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("SCRAPERAPI_KEY", raising=False)
    try:
        ScraperAPIClient()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "SCRAPERAPI_KEY" in str(e)
