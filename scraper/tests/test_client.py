import os

import responses

from scraper.src.client import AuthError, ScraperAPIClient, ScraperAPIError


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
def test_fetch_raises_QuotaExhaustedError_on_403():
    from scraper.src.client import QuotaExhaustedError
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="You have exhausted credits",
        status=403,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised QuotaExhaustedError"
    except QuotaExhaustedError as e:
        assert "Credits exhausted" in str(e)


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


@responses.activate
def test_fetch_raises_AuthError_on_401():
    from scraper.src.client import AuthError
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="Unauthorized, please check your API key",
        status=401,
    )
    client = ScraperAPIClient(api_key="bad-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised AuthError"
    except AuthError as e:
        assert "Invalid API key" in str(e)


def test_AuthError_is_ScraperAPIError_subclass():
    from scraper.src.client import AuthError
    assert issubclass(AuthError, ScraperAPIError)


def test_QuotaExhaustedError_is_ScraperAPIError_subclass():
    from scraper.src.client import QuotaExhaustedError
    assert issubclass(QuotaExhaustedError, ScraperAPIError)


@responses.activate
def test_get_account_returns_parsed_json():
    payload = {
        "concurrencyLimit": 5,
        "concurrentRequests": 0,
        "requestCount": 100,
        "requestLimit": 5000,
    }
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        json=payload,
        status=200,
    )
    client = ScraperAPIClient(api_key="test-key")
    result = client.get_account()
    assert result == payload
    assert responses.calls[0].request.params["api_key"] == "test-key"


@responses.activate
def test_get_account_raises_AuthError_on_401():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        body="Unauthorized",
        status=401,
    )
    client = ScraperAPIClient(api_key="bad-key")
    try:
        client.get_account()
        assert False, "Should have raised AuthError"
    except AuthError as e:
        assert "Invalid API key" in str(e)


@responses.activate
def test_get_account_raises_ScraperAPIError_on_500():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        body="Server error",
        status=500,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.get_account()
        assert False, "Should have raised ScraperAPIError"
    except ScraperAPIError as e:
        assert "/account returned 500" in str(e)
