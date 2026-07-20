from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "jsonld"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_type_names_handles_missing_and_url_prefix():
    """type_names yields bare names from @type as string, list, or URL;
    objects without @type yield nothing."""
    from scraper.structured import type_names
    assert list(type_names({})) == []
    assert list(type_names({"@type": None})) == []
    assert list(type_names({"@type": "Recipe"})) == ["Recipe"]
    assert list(type_names({"@type": "http://schema.org/Recipe"})) == ["Recipe"]
    assert list(type_names({"@type": ["Recipe", "https://schema.org/Thing"]})) == ["Recipe", "Thing"]
