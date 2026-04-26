from ingredients.parser import parse


def test_topup_basic():
    r = parse("Top up with Brut sparkling wine")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.amount is None
    assert r.unit is None
    assert r.name == "brut sparkling wine"


def test_topup_case_insensitive():
    r = parse("top up with ginger beer")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.name == "ginger beer"


def test_topup_with_parenthetical():
    r = parse("Top up with Soda (club soda) water")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.name == "soda (club soda) water"


def test_topup_empty_name_abstains():
    r = parse("Top up with")
    assert r.parse_status == "unparseable"


def test_topup_does_not_match_just_top():
    r = parse("Topping: cherries")
    assert r.parse_status == "unparseable"
