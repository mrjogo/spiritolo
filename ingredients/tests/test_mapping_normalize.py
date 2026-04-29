from ingredients.mapping.normalize import normalize_name


def test_lowercases_and_trims():
    assert normalize_name("  Lemon Juice  ") == "lemon juice"


def test_collapses_internal_whitespace():
    assert normalize_name("simple   syrup") == "simple syrup"


def test_returns_empty_string_for_none():
    assert normalize_name(None) == ""


def test_does_not_strip_punctuation_or_diacritics():
    # Form-node decisions depend on punctuation (e.g. "lemon, juiced").
    # Diacritics distinguish jalapeño from jalapeno in alias seed.
    assert normalize_name("Jalapeño Tincture") == "jalapeño tincture"
    assert normalize_name("Lemon, juiced") == "lemon, juiced"
