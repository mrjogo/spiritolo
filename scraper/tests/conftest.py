import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Yield a path to a temporary SQLite database file."""
    return tmp_path / "test_scraper.db"


@pytest.fixture
def sample_recipe_html():
    """Minimal HTML that contains valid Recipe JSON-LD."""
    padding = "<!-- " + ("x" * 100) + " -->\n"
    body_padding = ("<p>The Classic Margarita is a timeless tequila cocktail with a perfect balance of "
                    "sweet and sour flavors, finished with a salted rim.</p>\n") * 40
    return """<!DOCTYPE html>
<html>
<head><title>Classic Margarita</title></head>
<body>
<h1>Classic Margarita</h1>
<p>A timeless tequila cocktail.</p>
""" + body_padding + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Classic Margarita",
    "recipeIngredient": ["2 oz tequila", "1 oz lime juice", "1 oz triple sec"],
    "recipeInstructions": "Shake with ice, strain into glass."
}
</script>
</body>
</html>"""


@pytest.fixture
def sample_blocked_html():
    """HTML that looks like a Cloudflare challenge page."""
    return """<!DOCTYPE html>
<html>
<head><title>Just a moment...</title></head>
<body>
<div class="cf-challenge-running">Checking if the site connection is secure</div>
</body>
</html>"""


@pytest.fixture
def sample_empty_shell_html():
    """HTML from a JS-rendered page that didn't execute."""
    return """<!DOCTYPE html>
<html>
<head><title>Recipes</title></head>
<body><div id="root"></div><noscript>You need to enable JavaScript to run this app.</noscript></body>
</html>"""


@pytest.fixture
def sample_soft_404_html():
    """HTML that returned 200 but is actually a not-found page."""
    return """<!DOCTYPE html>
<html>
<head><title>Page Not Found</title><meta name="robots" content="noindex"></head>
<body>
<h1>404</h1>
<p>The page you're looking for doesn't exist or has been removed.</p>
</body>
</html>"""


@pytest.fixture
def sample_drink_recipe_html():
    """Recipe HTML with JSON-LD that has drink signals in recipeCategory."""
    body = "<p>A classic cocktail.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Classic Margarita</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Classic Margarita",
    "recipeCategory": "Cocktail",
    "keywords": "tequila, lime",
    "recipeIngredient": ["2 oz tequila", "1 oz lime juice"]
}
</script>
</body>
</html>"""


@pytest.fixture
def sample_food_recipe_html():
    """Recipe HTML with JSON-LD that has no drink signals."""
    body = "<p>A hearty dinner recipe.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Grilled Salmon</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Grilled Salmon",
    "recipeCategory": "Dinner, Main Course",
    "keywords": "salmon, grilled, healthy",
    "recipeIngredient": ["1 lb salmon", "2 tbsp olive oil"]
}
</script>
</body>
</html>"""


@pytest.fixture
def sample_drink_breadcrumb_html():
    """Recipe HTML where the drink signal is in the breadcrumb, not recipeCategory."""
    body = "<p>A refreshing gin cocktail.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Negroni</title></head>
<body>
""" + body + """<script type="application/ld+json">
[{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Negroni",
    "recipeCategory": "Gin",
    "keywords": "campari, vermouth",
    "mainEntityOfPage": {
        "@type": "WebPage",
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "item": {"name": "Recipes"}},
                {"@type": "ListItem", "position": 2, "item": {"name": "Drinks"}},
                {"@type": "ListItem", "position": 3, "item": {"name": "Cocktails"}}
            ]
        }
    }
}]
</script>
</body>
</html>"""


@pytest.fixture
def sample_drink_keywords_html():
    """Recipe HTML where the drink signal is only in keywords."""
    body = "<p>An easy party drink.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Espresso Martini</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Espresso Martini",
    "recipeCategory": "Vodka",
    "keywords": "beverages, cocktails, party-food"
}
</script>
</body>
</html>"""


@pytest.fixture
def make_mock_client():
    """Factory that returns a MagicMock with get_account() returning a sensible default."""
    from unittest.mock import MagicMock

    def _make(concurrency: int = 1, request_count: int = 0, request_limit: int = 5000):
        m = MagicMock()
        m.get_account.return_value = {
            "concurrencyLimit": concurrency,
            "concurrentRequests": 0,
            "requestCount": request_count,
            "requestLimit": request_limit,
            "burst": 0,
            "failedRequestCount": 0,
        }
        return m

    return _make
