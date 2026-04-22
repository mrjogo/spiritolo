from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "jsonld"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_standard_recipe():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("standard.html"))
    assert r["@type"] == "Recipe"
    assert r["name"] == "Negroni"
    assert r["recipeIngredient"] == ["1 oz gin", "1 oz campari", "1 oz sweet vermouth"]


def test_graph_wrapper():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("graph_wrapper.html"))
    assert r["name"] == "Old Fashioned"


def test_multiple_scripts_picks_recipe():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("multiple_scripts.html"))
    assert r["name"] == "Martini"


def test_type_as_array():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("type_as_array.html"))
    assert r["name"] == "Daiquiri"


def test_top_level_array():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("top_level_array.html"))
    assert r["name"] == "Manhattan"


def test_no_jsonld_returns_none():
    from scraper.src.jsonld import parse_recipe_from_html
    assert parse_recipe_from_html(load("no_jsonld.html")) is None


def test_malformed_then_valid():
    from scraper.src.jsonld import parse_recipe_from_html
    r = parse_recipe_from_html(load("malformed_then_valid.html"))
    assert r["name"] == "Sidecar"


def test_promoted_field_derivation_author():
    """The parser itself doesn't derive — it returns the raw dict. Promotion is the caller's job."""
    from scraper.src.jsonld import parse_recipe_from_html, derive_author
    r = parse_recipe_from_html(load("standard.html"))
    assert derive_author(r) == "Count Negroni"
    r2 = parse_recipe_from_html(load("author_bare_string.html"))
    assert derive_author(r2) == "Raymond Chandler"


def test_promoted_field_derivation_image_url():
    from scraper.src.jsonld import parse_recipe_from_html, derive_image_url
    r_str = parse_recipe_from_html(load("standard.html"))
    assert derive_image_url(r_str) == "https://example.com/negroni.jpg"
    r_obj = parse_recipe_from_html(load("image_as_object.html"))
    assert derive_image_url(r_obj) == "https://example.com/mojito.jpg"
    r_arr = parse_recipe_from_html(load("image_as_array.html"))
    assert derive_image_url(r_arr) == "https://example.com/mai-tai-1.jpg"


def test_promoted_field_derivation_image_array_of_objects():
    from scraper.src.jsonld import parse_recipe_from_html, derive_image_url
    r = parse_recipe_from_html(load("image_array_of_objects.html"))
    assert derive_image_url(r) == "https://example.com/vesper-1.jpg"


def test_promoted_field_derivation_image_missing():
    from scraper.src.jsonld import derive_image_url
    assert derive_image_url({"name": "No image"}) is None


def test_promoted_field_derivation_author_missing():
    from scraper.src.jsonld import derive_author
    assert derive_author({"name": "No author"}) is None
