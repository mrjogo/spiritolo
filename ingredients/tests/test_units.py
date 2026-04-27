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
    assert canonicalize_unit("shot") == "shot"
    assert canonicalize_unit("shots") == "shot"
    assert canonicalize_unit("bottle") == "bottle"
    assert canonicalize_unit("Bottles") == "bottle"
    assert canonicalize_unit("bunch") == "bunch"
    assert canonicalize_unit("bunches") == "bunch"


def test_canonicalize_unit_volume_extended():
    assert canonicalize_unit("pint") == "pint"
    assert canonicalize_unit("pints") == "pint"
    assert canonicalize_unit("pt") == "pint"
    assert canonicalize_unit("quart") == "quart"
    assert canonicalize_unit("quarts") == "quart"
    assert canonicalize_unit("qt") == "quart"
    assert canonicalize_unit("milliliter") == "ml"
    assert canonicalize_unit("Milliliters") == "ml"


def test_canonicalize_unit_weight():
    assert canonicalize_unit("g") == "g"
    assert canonicalize_unit("gram") == "g"
    assert canonicalize_unit("grams") == "g"
    assert canonicalize_unit("kg") == "kg"
    assert canonicalize_unit("kilogram") == "kg"
    assert canonicalize_unit("kilograms") == "kg"
    assert canonicalize_unit("lb") == "lb"
    assert canonicalize_unit("lbs") == "lb"
    assert canonicalize_unit("pound") == "lb"
    assert canonicalize_unit("Pounds") == "lb"


def test_canonicalize_unit_unknown_returns_none():
    assert canonicalize_unit("handful") is None
    assert canonicalize_unit("") is None
    assert canonicalize_unit("bourbon") is None


def test_is_unit_alias():
    assert is_unit_alias("oz")
    assert is_unit_alias("OUNCES")
    assert not is_unit_alias("handful")


def test_canonicalize_count_noun():
    assert canonicalize_count_noun("leaf") == "leaf"
    assert canonicalize_count_noun("leaves") == "leaf"
    assert canonicalize_count_noun("Slice") == "slice"
    assert canonicalize_count_noun("wedges") == "wedge"
    assert canonicalize_count_noun("cubes") == "cube"
    assert canonicalize_count_noun("egg white") == "egg white"
    assert canonicalize_count_noun("sprigs") == "sprig"
    # citrus + new produce/spice heads added in v3.
    assert canonicalize_count_noun("lemon") == "lemon"
    assert canonicalize_count_noun("Limes") == "lime"
    assert canonicalize_count_noun("oranges") == "orange"
    assert canonicalize_count_noun("clove") == "clove"
    assert canonicalize_count_noun("cloves") == "clove"
    assert canonicalize_count_noun("pod") == "pod"
    assert canonicalize_count_noun("pods") == "pod"
    assert canonicalize_count_noun("bean") == "bean"
    assert canonicalize_count_noun("beans") == "bean"
    assert canonicalize_count_noun("cherry") == "cherry"
    assert canonicalize_count_noun("cherries") == "cherry"
    assert canonicalize_count_noun("scoops") == "scoop"


def test_canonicalize_unit_bar_spoon_alias():
    # Two-word alias for the existing single-word `barspoon` canonical.
    assert canonicalize_unit("bar spoon") == "barspoon"
    assert canonicalize_unit("bar spoons") == "barspoon"
    # Both canonical and `can` (container) seen alongside.
    assert canonicalize_unit("can") == "can"
    assert canonicalize_unit("cans") == "can"


def test_canonicalize_count_noun_unknown_returns_none():
    assert canonicalize_count_noun("bourbon") is None
    assert canonicalize_count_noun("") is None


def test_is_count_noun_alias():
    assert is_count_noun_alias("leaves")
    assert not is_count_noun_alias("oz")
