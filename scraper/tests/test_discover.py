import responses

from scraper.src.client import ScraperAPIClient
from scraper.src.db import Database
from scraper.src.discover import discover_sitemap, discover_crawl, load_sites_config, run_discovery


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


SAMPLE_CRAWL_PAGE_1 = """<html><body>
<a href="https://example.com/recipes/margarita">Margarita</a>
<a href="https://example.com/recipes/mojito">Mojito</a>
<a href="https://example.com/about">About</a>
<a class="next-page" href="https://example.com/recipes?page=2">Next</a>
</body></html>"""


SAMPLE_CRAWL_PAGE_2 = """<html><body>
<a href="https://example.com/recipes/negroni">Negroni</a>
<a href="https://example.com/recipes/mojito">Mojito</a>
</body></html>"""


@responses.activate
def test_discover_sitemap_filters_by_pattern(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml", "/cocktails/recipe/")

    assert count == 3
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert "https://example.com/cocktails/recipe/margarita" in urls
    assert "https://example.com/cocktails/recipe/mojito" in urls
    assert "https://example.com/cocktails/recipe/negroni" in urls
    assert "https://example.com/about" not in urls
    db.close()


@responses.activate
def test_discover_sitemap_handles_sitemap_index(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_INDEX, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_RECIPES, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP_ARTICLES, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml", "/recipes/")

    assert count == 2
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert "https://example.com/recipes/daiquiri" in urls
    assert "https://example.com/recipes/old-fashioned" in urls
    db.close()


@responses.activate
def test_discover_crawl_follows_pagination(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_CRAWL_PAGE_1, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_CRAWL_PAGE_2, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    count = discover_crawl(
        client, db, "testsite",
        start_url="https://example.com/recipes",
        url_pattern="/recipes/",
        next_page_selector="a.next-page",
    )

    assert count == 3  # margarita, mojito, negroni (mojito deduped)
    pending = db.get_pending()
    urls = [row["url"] for row in pending]
    assert len(urls) == 3
    db.close()


def test_load_sites_config(tmp_path):
    config_file = tmp_path / "sites.yaml"
    config_file.write_text("""sites:
  - name: testsite
    domain: example.com
    discovery:
      method: sitemap
      sitemap_url: https://example.com/sitemap.xml
      url_pattern: "/recipes/"
""")
    sites = load_sites_config(config_file)
    assert len(sites) == 1
    assert sites[0]["name"] == "testsite"
    assert sites[0]["discovery"]["method"] == "sitemap"


@responses.activate
def test_discover_sitemap_is_idempotent(tmp_db):
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=SAMPLE_SITEMAP, status=200)
    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml", "/cocktails/recipe/")
    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml", "/cocktails/recipe/")

    assert count == 0  # all already exist
    pending = db.get_pending()
    assert len(pending) == 3  # no duplicates
    db.close()
