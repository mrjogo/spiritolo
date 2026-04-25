from ingredients.units import (
    canonicalize_unit,
    canonicalize_count_noun,
    is_unit_alias,
    is_count_noun_alias,
)


def test_canonicalize_unit_volume_aliases():
    assert canonicalize_unit("oz") == "oz"
    assert canonicalize_unit("oz.") == "oz"
    assert canonicalize_unit("ounce") == "oz"
    assert canonicalize_unit("Ounces") == "oz"
    assert canonicalize_unit("fl oz") == "oz"
    assert canonicalize_unit("ml") == "ml"
    assert canonicalize_unit("mL") == "ml"
    assert canonicalize_unit("cl") == "cl"
    assert canonicalize_unit("tsp") == "tsp"
    assert canonicalize_unit("teaspoon") == "tsp"
    assert canonicalize_unit("tablespoons") == "tbsp"
    assert canonicalize_unit("cup") == "cup"
    assert canonicalize_unit("cups") == "cup"


def test_canonicalize_unit_bartending():
    assert canonicalize_unit("dash") == "dash"
    assert canonicalize_unit("dashes") == "dash"
    assert canonicalize_unit("drop") == "drop"
    assert canonicalize_unit("drops") == "drop"
    assert canonicalize_unit("splash") == "splash"
    assert canonicalize_unit("barspoon") == "barspoon"
    assert canonicalize_unit("pinch") == "pinch"
    assert canonicalize_unit("part") == "part"
    assert canonicalize_unit("parts") == "part"


def test_canonicalize_unit_unknown_returns_none():
    assert canonicalize_unit("squeeze") is None
    assert canonicalize_unit("handful") is None
    assert canonicalize_unit("") is None
    assert canonicalize_unit("bourbon") is None


def test_is_unit_alias():
    assert is_unit_alias("oz")
    assert is_unit_alias("OUNCES")
    assert not is_unit_alias("squeeze")


def test_canonicalize_count_noun():
    assert canonicalize_count_noun("leaf") == "leaf"
    assert canonicalize_count_noun("leaves") == "leaf"
    assert canonicalize_count_noun("Slice") == "slice"
    assert canonicalize_count_noun("wedges") == "wedge"
    assert canonicalize_count_noun("cubes") == "cube"
    assert canonicalize_count_noun("egg white") == "egg white"
    assert canonicalize_count_noun("sprigs") == "sprig"


def test_canonicalize_count_noun_unknown_returns_none():
    assert canonicalize_count_noun("bourbon") is None
    assert canonicalize_count_noun("") is None


def test_is_count_noun_alias():
    assert is_count_noun_alias("leaves")
    assert not is_count_noun_alias("oz")
