from ingredients.parser import parse


def _assert_parsed(r, *, amount, unit, name):
    assert r.parse_status == "parsed", f"unexpected unparseable: {r}"
    assert r.parser_rule == "count_noun", f"wrong rule: {r.parser_rule}"
    assert r.amount == amount
    assert r.unit == unit
    assert r.name == name


def test_basic_count_noun_after_qualifier():
    _assert_parsed(parse("3 fresh basil leaves"),
                   amount=3.0, unit="leaf", name="basil")


def test_count_noun_no_qualifier():
    _assert_parsed(parse("4 sugar cubes"),
                   amount=4.0, unit="cube", name="sugar")


def test_dried_qualifier_with_no_real_count_noun_abstains():
    """'2 dried Star anise' has no count noun -> unparseable."""
    r = parse("2 dried Star anise")
    assert r.parse_status == "unparseable"


def test_pineapple_not_a_count_noun_abstains():
    r = parse("1 whole Pineapple")
    assert r.parse_status == "unparseable"


def test_egg_white_with_no_name_abstains():
    """'1 egg white' would parse to empty name; we abstain rather than store."""
    r = parse("1 egg white")
    assert r.parse_status == "unparseable"


def test_sprig_qualifier():
    _assert_parsed(parse("1 fresh rosemary sprig"),
                   amount=1.0, unit="sprig", name="rosemary")


def test_lime_wedge():
    _assert_parsed(parse("1 lime wedge"),
                   amount=1.0, unit="wedge", name="lime")


def test_count_noun_at_end_with_qualifier():
    _assert_parsed(parse("1 fresh Mint leaves"),
                   amount=1.0, unit="leaf", name="mint")


def test_count_noun_multi_word_name():
    _assert_parsed(parse("3 fresh sage leaves"),
                   amount=3.0, unit="leaf", name="sage")


def test_unknown_count_noun_abstains():
    r = parse("3 dollops cream")
    assert r.parse_status == "unparseable"
