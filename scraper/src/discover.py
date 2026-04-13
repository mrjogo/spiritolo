import argparse
import re
from pathlib import Path

import requests
import yaml
from lxml import etree

from scraper.src.client import USER_AGENT, ScraperAPIClient
from scraper.src.db import Database

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"


def load_sites_config(config_path: Path) -> list[dict]:
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config["sites"]


class SmartFetcher:
    """Fetch URLs directly first, falling back to ScraperAPI. Auto-upgrades to
    proxy-only after 2 consecutive direct failures."""

    UPGRADE_THRESHOLD = 2

    def __init__(self, client: ScraperAPIClient):
        self.client = client
        self.consecutive_failures = 0
        self.proxy_only = False

    def _is_valid_xml(self, text: str) -> bool:
        return "<?xml" in text[:100] or "<urlset" in text[:200] or "<sitemapindex" in text[:200]

    def fetch(self, url: str) -> str:
        if not self.proxy_only:
            try:
                resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
                if resp.status_code == 200 and self._is_valid_xml(resp.text):
                    self.consecutive_failures = 0
                    return resp.text
            except requests.RequestException:
                pass
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.UPGRADE_THRESHOLD:
                self.proxy_only = True
                print("  Upgraded to ScraperAPI-only (2 consecutive direct failures)")
        return self.client.fetch(url)


def probe_sitemap(domain: str, fetcher: SmartFetcher | None = None, timeout: int = 10) -> str | None:
    """Check robots.txt and /sitemap.xml for a sitemap URL. Returns URL or None."""
    # Don't add www. if domain already has a subdomain (e.g. cooking.nytimes.com)
    parts = domain.split(".")
    if len(parts) > 2:
        base = f"https://{domain}"
    else:
        base = f"https://www.{domain}"

    if fetcher:
        # Use SmartFetcher for robots.txt
        try:
            text = fetcher.fetch(f"{base}/robots.txt")
            for match in re.finditer(r"^Sitemap:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE):
                return match.group(1)
        except Exception:
            pass
        # Try /sitemap.xml
        try:
            text = fetcher.fetch(f"{base}/sitemap.xml")
            if "<?xml" in text[:100]:
                return f"{base}/sitemap.xml"
        except Exception:
            pass
    else:
        # Legacy path: plain requests only (for tests that don't pass a fetcher)
        headers = {"User-Agent": USER_AGENT}
        try:
            resp = requests.get(f"{base}/robots.txt", headers=headers, timeout=timeout)
            if resp.status_code == 200:
                for match in re.finditer(r"^Sitemap:\s*(\S+)", resp.text, re.MULTILINE | re.IGNORECASE):
                    return match.group(1)
        except requests.RequestException:
            pass
        try:
            resp = requests.get(f"{base}/sitemap.xml", headers=headers, timeout=timeout)
            if resp.status_code == 200 and "<?xml" in resp.text[:100]:
                return f"{base}/sitemap.xml"
        except requests.RequestException:
            pass

    return None


def discover_sitemap(
    client: ScraperAPIClient,
    db: Database,
    site_name: str,
    sitemap_url: str,
    fetcher: SmartFetcher | None = None,
) -> int:
    """Fetch sitemap, add all URLs to database. Returns count of new URLs added."""
    _fetcher = fetcher or SmartFetcher(client)
    print(f"  Fetching {sitemap_url}")
    try:
        xml_text = _fetcher.fetch(sitemap_url)
    except Exception as e:
        print(f"  ERROR fetching {sitemap_url}: {e}")
        return 0
    root = etree.fromstring(xml_text.encode("utf-8"))

    # Check if this is a sitemap index
    sub_sitemaps = root.xpath("//sm:sitemap/sm:loc/text()", namespaces=SITEMAP_NS)
    if sub_sitemaps:
        print(f"  Sitemap index with {len(sub_sitemaps)} sub-sitemaps")
        total = 0
        for i, sub_url in enumerate(sub_sitemaps, 1):
            total += discover_sitemap(client, db, site_name, sub_url, fetcher=_fetcher)
            print(f"  [{i}/{len(sub_sitemaps)}] {total} URLs so far")
        return total

    # Regular sitemap — extract and batch insert all URLs
    locs = root.xpath("//sm:url/sm:loc/text()", namespaces=SITEMAP_NS)
    if not locs:
        return 0
    return db.add_urls_batch(site_name, locs, sitemap_source=sitemap_url)



def run_probe(site_filter: str | None = None, config_path: Path = DEFAULT_CONFIG_PATH):
    """Probe all sites for sitemaps and update sites.yaml with results."""
    config = load_sites_config(config_path)
    client = ScraperAPIClient()
    updated = False

    for site in config:
        if site_filter and site["name"] != site_filter:
            continue

        name = site["name"]
        domain = site["domain"]

        if site.get("sitemap_url"):
            print(f"[{name}] Already has sitemap_url: {site['sitemap_url']}")
            continue

        print(f"[{name}] Probing {domain} for sitemap...")
        fetcher = SmartFetcher(client)
        url = probe_sitemap(domain, fetcher=fetcher)
        if url:
            site["sitemap_url"] = url
            updated = True
            print(f"[{name}] Found sitemap: {url}")
        else:
            print(f"[{name}] No sitemap found")

    if updated:
        with open(config_path, "w") as f:
            yaml.dump({"sites": config}, f, default_flow_style=False, sort_keys=False)
        print(f"\nUpdated {config_path}")


def run_discovery(site_filter: str | None = None):
    config = load_sites_config(DEFAULT_CONFIG_PATH)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(DEFAULT_DB_PATH)
    client = ScraperAPIClient()

    for site in config:
        if site_filter and site["name"] != site_filter:
            continue

        name = site["name"]

        if "sitemap_url" not in site:
            raise ValueError(f"[{name}] Missing required sitemap_url in sites.yaml")

        print(f"[{name}] Discovering URLs...")
        fetcher = SmartFetcher(client)
        count = discover_sitemap(client, db, name, site["sitemap_url"], fetcher=fetcher)
        print(f"[{name}] Added {count} new URLs")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover recipe URLs from configured sites")
    parser.add_argument("--site", help="Only run for a specific site")
    parser.add_argument("--probe", action="store_true", help="Probe sites for sitemaps and update sites.yaml")
    args = parser.parse_args()

    if args.probe:
        run_probe(site_filter=args.site)
    else:
        run_discovery(site_filter=args.site)
