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


def probe_sitemap(domain: str, timeout: int = 10) -> str | None:
    """Check robots.txt and /sitemap.xml for a sitemap URL. Returns URL or None.

    Uses plain requests (no ScraperAPI) since these are public endpoints.
    """
    # Don't add www. if domain already has a subdomain (e.g. cooking.nytimes.com)
    parts = domain.split(".")
    if len(parts) > 2:
        base = f"https://{domain}"
    else:
        base = f"https://www.{domain}"

    headers = {"User-Agent": USER_AGENT}

    # 1. Check robots.txt for Sitemap: directives
    try:
        resp = requests.get(f"{base}/robots.txt", headers=headers, timeout=timeout)
        if resp.status_code == 200:
            for match in re.finditer(r"^Sitemap:\s*(\S+)", resp.text, re.MULTILINE | re.IGNORECASE):
                return match.group(1)
    except requests.RequestException:
        pass

    # 2. Try /sitemap.xml directly
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
    url_pattern: str,
) -> int:
    """Fetch sitemap, filter URLs by pattern, add to database. Returns count of new URLs added."""
    xml_text = client.fetch(sitemap_url)
    root = etree.fromstring(xml_text.encode("utf-8"))

    # Check if this is a sitemap index
    sub_sitemaps = root.xpath("//sm:sitemap/sm:loc/text()", namespaces=SITEMAP_NS)
    if sub_sitemaps:
        total = 0
        for sub_url in sub_sitemaps:
            total += discover_sitemap(client, db, site_name, sub_url, url_pattern)
        return total

    # Regular sitemap — extract URLs
    locs = root.xpath("//sm:url/sm:loc/text()", namespaces=SITEMAP_NS)
    added = 0
    for loc in locs:
        if url_pattern in loc:
            if db.add_url(site_name, loc):
                added += 1
    return added



def run_probe(site_filter: str | None = None, config_path: Path = DEFAULT_CONFIG_PATH):
    """Probe all sites for sitemaps and update sites.yaml with results."""
    config = load_sites_config(config_path)
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
        url = probe_sitemap(domain)
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
        url_pattern = site["url_pattern"]

        if "sitemap_url" not in site:
            raise ValueError(f"[{name}] Missing required sitemap_url in sites.yaml")

        print(f"[{name}] Discovering URLs...")
        count = discover_sitemap(client, db, name, site["sitemap_url"], url_pattern)
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
