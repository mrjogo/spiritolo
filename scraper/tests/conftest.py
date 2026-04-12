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
