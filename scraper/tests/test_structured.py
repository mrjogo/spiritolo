from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "jsonld"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_standard_recipe():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("standard.html"))
    assert r["@type"] == "Recipe"
    assert r["name"] == "Negroni"
    assert r["recipeIngredient"] == ["1 oz gin", "1 oz campari", "1 oz sweet vermouth"]


def test_graph_wrapper():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("graph_wrapper.html"))
    assert r["name"] == "Old Fashioned"


def test_multiple_scripts_picks_recipe():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("multiple_scripts.html"))
    assert r["name"] == "Martini"


def test_type_as_array():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("type_as_array.html"))
    assert r["name"] == "Daiquiri"


def test_top_level_array():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("top_level_array.html"))
    assert r["name"] == "Manhattan"


def test_no_structured_returns_none():
    from scraper.src.structured import find_recipe
    assert find_recipe(load("no_jsonld.html")) is None


def test_malformed_then_valid():
    from scraper.src.structured import find_recipe
    r = find_recipe(load("malformed_then_valid.html"))
    assert r["name"] == "Sidecar"


def test_microdata_recipe_normalized_to_jsonld_shape():
    """Punchdrink-style pages expose Recipe via HTML microdata. After normalization
    the dict looks like JSON-LD: bare @type string, single-valued props unwrapped
    from lists, nested Person item reshaped into a flat dict with @type."""
    from scraper.src.structured import find_recipe
    from scraper.src.extract import derive_author, derive_image_url, derive_name
    r = find_recipe(load("microdata.html"))
    assert r is not None
    assert r["@type"] == "Recipe"
    assert r["name"] == "Senorita Spritz"  # unwrapped from single-element list
    assert r["recipeIngredient"] == ["1 oz gin", "1 oz campari", "1 oz sweet vermouth"]
    # Nested Person microdata item flattened to JSON-LD shape.
    assert r["author"] == {"@type": "Person", "name": "Punch Staff"}
    # Derives work off the normalized shape.
    assert derive_name(r) == "Senorita Spritz"
    assert derive_author(r) == "Punch Staff"
    assert derive_image_url(r) == "https://example.com/spritz.jpg"


def test_promoted_field_derivation_author():
    """Derivation is extract's job — the parser returns the raw dict."""
    from scraper.src.structured import find_recipe
    from scraper.src.extract import derive_author
    r = find_recipe(load("standard.html"))
    assert derive_author(r) == "Count Negroni"
    r2 = find_recipe(load("author_bare_string.html"))
    assert derive_author(r2) == "Raymond Chandler"


def test_promoted_field_derivation_image_url():
    from scraper.src.structured import find_recipe
    from scraper.src.extract import derive_image_url
    r_str = find_recipe(load("standard.html"))
    assert derive_image_url(r_str) == "https://example.com/negroni.jpg"
    r_obj = find_recipe(load("image_as_object.html"))
    assert derive_image_url(r_obj) == "https://example.com/mojito.jpg"
    r_arr = find_recipe(load("image_as_array.html"))
    assert derive_image_url(r_arr) == "https://example.com/mai-tai-1.jpg"


def test_promoted_field_derivation_image_array_of_objects():
    from scraper.src.structured import find_recipe
    from scraper.src.extract import derive_image_url
    r = find_recipe(load("image_array_of_objects.html"))
    assert derive_image_url(r) == "https://example.com/vesper-1.jpg"


def test_promoted_field_derivation_image_missing():
    from scraper.src.extract import derive_image_url
    assert derive_image_url({"name": "No image"}) is None


def test_promoted_field_derivation_author_missing():
    from scraper.src.extract import derive_author
    assert derive_author({"name": "No author"}) is None


def test_type_names_handles_missing_and_url_prefix():
    """type_names yields bare names from @type as string, list, or URL;
    objects without @type yield nothing."""
    from scraper.src.structured import type_names
    assert list(type_names({})) == []
    assert list(type_names({"@type": None})) == []
    assert list(type_names({"@type": "Recipe"})) == ["Recipe"]
    assert list(type_names({"@type": "http://schema.org/Recipe"})) == ["Recipe"]
    assert list(type_names({"@type": ["Recipe", "https://schema.org/Thing"]})) == ["Recipe", "Thing"]
