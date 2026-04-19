"""End-to-end test: discover URLs from a sitemap, fetch them, validate, and save HTML."""

import responses

from scraper.src.client import ScraperAPIClient
from scraper.src.db import Database
from scraper.src.discover import discover_sitemap
from scraper.src.fetch import fetch_pages


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/recipes/margarita</loc></url>
  <url><loc>https://example.com/recipes/mojito</loc></url>
  <url><loc>https://example.com/about</loc></url>
</urlset>"""


# Padded to exceed 5KB so it passes the size gate and JSON-LD check accepts it.
_RECIPE_PADDING = (
    "<p>The Classic Margarita is a timeless tequila cocktail with a perfect balance of "
    "sweet and sour flavors, finished with a salted rim. Originating in Mexico, this drink "
    "has become one of the most popular cocktails worldwide. The combination of tequila, "
    "fresh lime juice, and triple sec creates a refreshing balance that is hard to beat. "
    "Served over ice or blended, the margarita is perfect for any occasion.</p>\n"
) * 50  # ~4.5KB of padding to push total over 5KB

RECIPE_HTML = f"""<!DOCTYPE html>
<html>
<head><title>Margarita</title></head>
<body>
<h1>Margarita</h1>
{_RECIPE_PADDING}
<script type="application/ld+json">
{{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Margarita",
    "recipeIngredient": ["2 oz tequila", "1 oz lime juice", "1 oz triple sec"],
    "recipeInstructions": "Shake with ice."
}}
</script>
</body>
</html>"""


BLOCKED_HTML = """<!DOCTYPE html>
<html><body><div class="cf-challenge-running">Checking...</div></body></html>"""


@responses.activate
def test_full_pipeline(tmp_db, tmp_path):
    # Phase 1: Discovery — sitemap fetch
    responses.add(responses.GET, "https://api.scraperapi.com", body=SITEMAP, status=200)
    # Phase 2: Fetch — account info (called at fetch_pages startup)
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        json={
            "concurrencyLimit": 5,
            "concurrentRequests": 0,
            "requestCount": 100,
            "requestLimit": 10000,
            "burst": 10,
            "failedRequestCount": 0,
        },
        status=200,
    )
    # Phase 2: Fetch — two recipe pages
    responses.add(responses.GET, "https://api.scraperapi.com", body=RECIPE_HTML, status=200)
    responses.add(responses.GET, "https://api.scraperapi.com", body=BLOCKED_HTML, status=200)

    client = ScraperAPIClient(api_key="test-key")
    db = Database(tmp_db)

    # Discover — all 3 URLs are added (no url_pattern filtering)
    count = discover_sitemap(client, db, "testsite", "https://example.com/sitemap.xml")
    assert count == 3

    # Set content_type so fetch picks up only the recipes
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
    db.set_content_type("https://example.com/recipes/mojito", "likely_drink_recipe")

    # Fetch
    results = fetch_pages(db, client, html_dir=tmp_path, delay=0)
    assert results["Recipe"] == 1
    assert results["blocked"] == 1

    # Verify state
    stats = db.get_stats()
    assert stats["testsite"]["Recipe"] == 1
    assert stats["testsite"]["blocked"] == 1

    # Verify HTML was saved for the fetched page
    html_files = list(tmp_path.glob("testsite/*.html"))
    assert len(html_files) == 1
    assert "Margarita" in html_files[0].read_text()

    db.close()
