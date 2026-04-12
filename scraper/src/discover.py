import argparse
from pathlib import Path

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
            existing = db.conn.execute("SELECT 1 FROM pages WHERE url = ?", (loc,)).fetchone()
            if not existing:
                db.add_url(site_name, loc)
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
                existing = db.conn.execute("SELECT 1 FROM pages WHERE url = ?", (link,)).fetchone()
                if not existing:
                    db.add_url(site_name, link)
                    added += 1

        # Follow pagination
        next_links = tree.cssselect(next_page_selector) if next_page_selector else []
        if next_links:
            current_url = next_links[0].get("href")
        else:
            current_url = None

    return added


def run_discovery(site_filter: str | None = None):
    config = load_sites_config(DEFAULT_CONFIG_PATH)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(DEFAULT_DB_PATH)
    client = ScraperAPIClient()

    for site in config:
        if site_filter and site["name"] != site_filter:
            continue

        discovery = site["discovery"]
        name = site["name"]
        print(f"[{name}] Discovering URLs...")

        if discovery["method"] == "sitemap":
            count = discover_sitemap(
                client, db, name, discovery["sitemap_url"], discovery["url_pattern"]
            )
        elif discovery["method"] == "crawl":
            count = discover_crawl(
                client, db, name,
                start_url=discovery["start_url"],
                url_pattern=discovery["url_pattern"],
                next_page_selector=discovery.get("next_page_selector", ""),
            )
        else:
            print(f"[{name}] Unknown discovery method: {discovery['method']}")
            continue

        print(f"[{name}] Added {count} new URLs")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover recipe URLs from configured sites")
    parser.add_argument("--site", help="Only discover for a specific site")
    args = parser.parse_args()
    run_discovery(site_filter=args.site)
