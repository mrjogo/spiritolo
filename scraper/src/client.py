import os

import requests


class ScraperAPIError(Exception):
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

        resp = requests.get(self.BASE_URL, params=params, timeout=60)
        if resp.status_code != 200:
            raise ScraperAPIError(
                f"ScraperAPI returned {resp.status_code} for {url}: {resp.text[:200]}"
            )
        return resp.text
