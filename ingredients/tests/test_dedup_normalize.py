import pytest
from ingredients.dedup.normalize import normalize_cocktail_name


@pytest.mark.parametrize("raw, expected", [
    ("Negroni", "negroni"),
    ("The Negroni", "negroni"),
    ("Classic Negroni", "negroni"),
    ("Negroni Cocktail", "negroni"),
    ("Best Negroni Recipe", "negroni"),
    ("Perfect Negroni", "negroni"),
    ("How to Make a Negroni", "negroni"),
    ("Negroni (Italian Aperitivo)", "negroni"),
    ("  Negroni  ", "negroni"),
    ("Old Fashioned", "old fashioned"),
    ("THE OLD FASHIONED", "old fashioned"),
    ("Old-Fashioned", "old fashioned"),
])
def test_normalize_strips_editorial_noise(raw, expected):
    assert normalize_cocktail_name(raw) == expected


def test_preserves_drink_modifier_prefixes():
    # Modifier prefixes that mark a real variant must NOT be stripped.
    assert normalize_cocktail_name("Mezcal Negroni") == "mezcal negroni"
    assert normalize_cocktail_name("Smoked Old Fashioned") == "smoked old fashioned"
    assert normalize_cocktail_name("Hemingway Daiquiri") == "hemingway daiquiri"
    assert normalize_cocktail_name("White Negroni") == "white negroni"


def test_handles_empty_or_none():
    assert normalize_cocktail_name(None) == ""
    assert normalize_cocktail_name("") == ""
    assert normalize_cocktail_name("   ") == ""


def test_strips_recipe_or_cocktail_when_trailing():
    assert normalize_cocktail_name("Manhattan Recipe") == "manhattan"
    assert normalize_cocktail_name("Manhattan Cocktail") == "manhattan"
    # But NOT in the middle (defensive against false-strip)
    assert normalize_cocktail_name("Recipe for Manhattan") == "manhattan"
