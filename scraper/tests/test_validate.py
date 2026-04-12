from scraper.src.validate import validate, ValidationResult


def test_valid_recipe_with_jsonld(sample_recipe_html):
    result = validate(sample_recipe_html)
    assert result.status == "Recipe"


def test_blocked_cloudflare(sample_blocked_html):
    result = validate(sample_blocked_html)
    assert result.status == "blocked"


def test_blocked_empty_shell(sample_empty_shell_html):
    result = validate(sample_empty_shell_html)
    assert result.status == "blocked"


def test_blocked_soft_404(sample_soft_404_html):
    result = validate(sample_soft_404_html)
    assert result.status == "blocked"


def test_blocked_tiny_page():
    tiny = "<html><body>x</body></html>"
    result = validate(tiny)
    assert result.status == "blocked"
    assert "size" in result.reason.lower()


def test_unverified_no_jsonld_but_has_content():
    html = "<html><head><title>My Cocktail</title></head><body>" + "<p>Mix ingredients together.</p>" * 200 + "</body></html>"
    result = validate(html)
    assert result.status == "unverified"


def test_blocked_captcha():
    padding = "<p>Please complete the challenge below to continue.</p>\n" * 100
    html = "<html><body>\n" + padding + """    <div class="g-recaptcha" data-sitekey="abc123"></div>
    <p>Please verify you are human.</p>
    </body></html>"""
    result = validate(html)
    assert result.status == "blocked"
    assert "recaptcha" in result.reason.lower()


def test_blocked_access_denied():
    html = "<html><body><h1>Access Denied</h1><p>You don't have permission.</p></body></html>"
    result = validate(html)
    assert result.status == "blocked"


def test_jsonld_non_recipe_type():
    html = """<html><body>
    <script type="application/ld+json">
    {"@type": "Article", "name": "Best Cocktails"}
    </script>
    """ + "<p>content</p>" * 500 + "</body></html>"
    result = validate(html)
    assert result.status == "Article"


def test_jsonld_itemlist_type():
    html = """<html><body>
    <script type="application/ld+json">
    {"@type": "ItemList", "name": "10 Summer Cocktails", "itemListElement": []}
    </script>
    """ + "<p>content</p>" * 500 + "</body></html>"
    result = validate(html)
    assert result.status == "ItemList"


def test_jsonld_list_type():
    """@type can be a list like ["Article", "NewsArticle"]."""
    html = """<html><body>
    <script type="application/ld+json">
    {"@type": ["Article", "NewsArticle"], "name": "Bar Review"}
    </script>
    """ + "<p>content</p>" * 500 + "</body></html>"
    result = validate(html)
    assert result.status == "Article"
