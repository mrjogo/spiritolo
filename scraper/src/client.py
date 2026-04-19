import os

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class ScraperAPIError(Exception):
    pass


class AuthError(ScraperAPIError):
    pass


class QuotaExhaustedError(ScraperAPIError):
    pass


class ScraperAPIClient:
    BASE_URL = "https://api.scraperapi.com"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SCRAPERAPI_KEY")
        if not self.api_key:
            raise ValueError(
                "No API key provided. Pass api_key or set SCRAPERAPI_KEY environment variable."
            )

    def fetch(self, url: str, render: bool = False) -> str:
        params = {
            "api_key": self.api_key,
            "url": url,
        }
        if render:
            params["render"] = "true"

        resp = requests.get(self.BASE_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=70)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 401:
            raise AuthError(f"Invalid API key: {resp.text[:200]}")
        if resp.status_code == 403:
            raise QuotaExhaustedError(f"Credits exhausted: {resp.text[:200]}")
        raise ScraperAPIError(
            f"ScraperAPI returned {resp.status_code} for {url}: {resp.text[:200]}"
        )
