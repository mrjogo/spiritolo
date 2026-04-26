from ingredients.parser import parse


def test_garnish_prefix_basic():
    r = parse("Garnish: lemon twist")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.amount is None
    assert r.unit is None
    assert r.name == "lemon twist"


def test_garnish_prefix_case_insensitive():
    r = parse("garnish: orange peel")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.name == "orange peel"


def test_garnish_prefix_with_extra_spaces():
    r = parse("Garnish:   pineapple leaf")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.name == "pineapple leaf"


def test_garnish_prefix_lowercases_name():
    r = parse("Garnish: Cinnamon Stick")
    assert r.name == "cinnamon stick"


def test_garnish_prefix_empty_name_abstains():
    """A bare 'Garnish:' with no text after must not parse to an empty name."""
    r = parse("Garnish:")
    assert r.parse_status == "unparseable"


def test_no_garnish_prefix_leaves_unparseable_for_now():
    """Other rules don't exist yet; non-matching strings stay unparseable."""
    r = parse("1 oz gin")
    assert r.parse_status == "unparseable"


def test_raw_text_preserved_on_parse():
    r = parse("Garnish: lemon twist")
    assert r.raw_text == "Garnish: lemon twist"


def test_raw_text_preserved_on_unparseable():
    r = parse("¯\\_(ツ)_/¯")
    assert r.raw_text == "¯\\_(ツ)_/¯"
    assert r.parse_status == "unparseable"
