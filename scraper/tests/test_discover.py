import requests
import responses

from scraper.src.client import ScraperAPIClient, ScraperAPIError
from scraper.src.db import Database
from scraper.src.discover import discover_sitemap, load_sites_config, probe_sitemap


SAMPLE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/cocktails/recipe/margarita</loc></url>
  <url><loc>https://example.com/cocktails/recipe/mojito</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/cocktails/recipe/negroni</loc></url>
</urlset>"""


SAMPLE_SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-recipes.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-articles.xml</loc></sitemap>
</sitemapindex>"""


SAMPLE_SITEMAP_RECIPES = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/recipes/daiquiri</loc></url>
  <url><loc>https://example.com/recipes/old-fashioned</loc></url>
</urlset>"""


SAMPLE_SITEMAP_ARTICLES = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/articles/best-bars</loc></url>
</urlset>"""


@responses.activate
def test_discover_sitemap_adds_all_urls(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")

    assert count == 4
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert "https://example.com/cocktails/recipe/margarita" in urls
    assert "https://example.com/cocktails/recipe/mojito" in urls
    assert "https://example.com/cocktails/recipe/negroni" in urls
    assert "https://example.com/about" in urls
    # All URLs should have sitemap_source set
    sources = [row["sitemap_source"] for row in pending]
    assert all(s == "https://example.com/sitemap.xml" for s in sources)
    db.close()


@responses.activate
def test_discover_sitemap_index_tracks_sub_sitemap_source(tmp_db):
    """Each URL should record which sub-sitemap it came from, not the index."""
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_INDEX, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_RECIPES, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_ARTICLES, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")

    row = db.conn.execute(
        "SELECT sitemap_source FROM pages WHERE url = ?",
        ("https://example.com/recipes/daiquiri",),
    ).fetchone()
    assert row["sitemap_source"] == "https://example.com/sitemap-recipes.xml"

    row = db.conn.execute(
        "SELECT sitemap_source FROM pages WHERE url = ?",
        ("https://example.com/articles/best-bars",),
    ).fetchone()
    assert row["sitemap_source"] == "https://example.com/sitemap-articles.xml"
    db.close()


@responses.activate
def test_discover_sitemap_handles_sitemap_index(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_INDEX, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_RECIPES, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_ARTICLES, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")

    assert count == 3
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert "https://example.com/recipes/daiquiri" in urls
    assert "https://example.com/recipes/old-fashioned" in urls
    assert "https://example.com/articles/best-bars" in urls
    db.close()


def test_load_sites_config(tmp_path):
    config_file = tmp_path / "sites.yaml"
    config_file.write_text("""sites:
  - name: testsite
    domain: example.com
    sitemap_url: https://example.com/sitemap.xml
""")
    sites = load_sites_config(config_file)
    assert len(sites) == 1
    assert sites[0]["name"] == "testsite"
    assert sites[0]["sitemap_url"] == "https://example.com/sitemap.xml"


@responses.activate
def test_discover_sitemap_is_idempotent(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")
    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")

    assert count == 0  # all already exist
    pending = db.get_pending()
    assert len(pending) == 4  # no duplicates
    db.close()


@responses.activate
def test_discover_sitemap_skips_failed_sub_sitemap(tmp_db):
    """If a sub-sitemap fetch fails, skip it and continue with the rest."""
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_INDEX, status=200)
    # First sub-sitemap times out
    responses.add(responses.GET, "https://api.scraperapi.com", body=requests.exceptions.ReadTimeout())
    # Second sub-sitemap succeeds
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_ARTICLES, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")

    # Should have the 1 URL from articles, despite recipes timing out
    assert count == 1
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert "https://example.com/articles/best-bars" in urls
    db.close()


@responses.activate
def test_probe_sitemap_from_robots_txt():
    responses.add(
        responses.GET,
        "https://www.example.com/robots.txt",
        body="User-agent: *\nDisallow: /admin/\nSitemap: https://www.example.com/sitemap.xml\n",
        status=200,
    )
    assert probe_sitemap("example.com") == "https://www.example.com/sitemap.xml"


@responses.activate
def test_probe_sitemap_from_direct_url():
    responses.add(responses.GET, "https://www.example.com/robots.txt", status=404)
    responses.add(
        responses.GET,
        "https://www.example.com/sitemap.xml",
        body='<?xml version="1.0"?><urlset></urlset>',
        status=200,
    )
    assert probe_sitemap("example.com") == "https://www.example.com/sitemap.xml"


@responses.activate
def test_probe_sitemap_not_found():
    responses.add(responses.GET, "https://www.example.com/robots.txt", status=404)
    responses.add(responses.GET, "https://www.example.com/sitemap.xml", status=404)
    assert probe_sitemap("example.com") is None
