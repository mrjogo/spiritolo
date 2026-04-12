import argparse
import re
from pathlib import Path

import requests
import yaml
from lxml import etree

from scraper.src.client import ScraperAPIClient
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
    base = f"https://www.{domain}"

    # 1. Check robots.txt for Sitemap: directives
    try:
        resp = requests.get(f"{base}/robots.txt", timeout=timeout)
        if resp.status_code == 200:
            for match in re.finditer(r"^Sitemap:\s*(\S+)", resp.text, re.MULTILINE | re.IGNORECASE):
                return match.group(1)
    except requests.RequestException:
        pass

    # 2. Try /sitemap.xml directly
    try:
        resp = requests.get(f"{base}/sitemap.xml", timeout=timeout)
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


def discover_crawl(
    client: ScraperAPIClient,
    db: Database,
    site_name: str,
    start_url: str,
    url_pattern: str,
    next_page_selector: str,
) -> int:
    """Crawl paginated index pages, extract recipe URLs, add to database. Returns count of new URLs added."""
    added = 0
    current_url = start_url
    seen_urls: set[str] = set()

    while current_url:
        html_text = client.fetch(current_url)
        tree = etree.HTML(html_text)

        # Extract recipe links
        links = tree.xpath("//a/@href")
        for link in links:
            if url_pattern in link and link not in seen_urls:
                seen_urls.add(link)
                if db.add_url(site_name, link):
                    added += 1

        # Follow pagination
        next_links = tree.cssselect(next_page_selector) if next_page_selector else []
        if next_links:
            current_url = next_links[0].get("href")
        else:
            current_url = None

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
        print(f"[{name}] Discovering URLs...")

        if site.get("sitemap_url"):
            # Known sitemap — use it, fail hard if broken
            count = discover_sitemap(client, db, name, site["sitemap_url"], url_pattern)
        else:
            # No known sitemap — probe first, fall back to crawl
            probed_url = probe_sitemap(site["domain"])
            if probed_url:
                print(f"[{name}] Found sitemap at {probed_url}")
                count = discover_sitemap(client, db, name, probed_url, url_pattern)
            elif site.get("start_url"):
                print(f"[{name}] No sitemap, falling back to crawl")
                count = discover_crawl(
                    client, db, name,
                    start_url=site["start_url"],
                    url_pattern=url_pattern,
                    next_page_selector=site.get("next_page_selector", ""),
                )
            else:
                print(f"[{name}] No sitemap found and no crawl config — skipping")
                continue

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
