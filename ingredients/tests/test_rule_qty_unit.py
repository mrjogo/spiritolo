from ingredients.parser import parse


def _assert_parsed(r, *, amount, unit, name, amount_max=None):
    assert r.parse_status == "parsed", f"unexpected unparseable: {r}"
    assert r.parser_rule == "qty_unit", f"wrong rule: {r.parser_rule}"
    assert r.amount == amount
    assert r.amount_max == amount_max
    assert r.unit == unit
    assert r.name == name


def test_simple_oz():
    _assert_parsed(parse("2 oz gin"), amount=2.0, unit="oz", name="gin")


def test_decimal_oz_period_alias():
    _assert_parsed(parse("0.5 oz. rye"), amount=0.5, unit="oz", name="rye")


def test_mixed_number_ounce_word():
    _assert_parsed(parse("1 1/2 ounces lime juice"), amount=1.5, unit="oz", name="lime juice")


def test_unicode_fraction_normalized_then_parsed():
    _assert_parsed(parse("¾ ounce campari"), amount=0.75, unit="oz", name="campari")


def test_ml_canonicalizes():
    _assert_parsed(parse("45 ml Light gold rum 1-3yo"),
                   amount=45.0, unit="ml", name="light gold rum 1-3yo")


def test_cl_canonicalizes():
    _assert_parsed(parse("4 cl gin"), amount=4.0, unit="cl", name="gin")


def test_teaspoon_canonicalizes():
    _assert_parsed(parse("1 teaspoon honey"), amount=1.0, unit="tsp", name="honey")
    _assert_parsed(parse("2 tsp. honey"), amount=2.0, unit="tsp", name="honey")


def test_tablespoon_canonicalizes():
    _assert_parsed(parse("3 tablespoons sugar"), amount=3.0, unit="tbsp", name="sugar")


def test_cup_canonicalizes():
    _assert_parsed(parse("1/4 cup honey"), amount=0.25, unit="cup", name="honey")


def test_dash_drop_splash():
    _assert_parsed(parse("1 dash Aromatic bitters"), amount=1.0, unit="dash", name="aromatic bitters")
    _assert_parsed(parse("3 drops Xocolatl mole bitters"), amount=3.0, unit="drop", name="xocolatl mole bitters")
    _assert_parsed(parse("1 splash soda"), amount=1.0, unit="splash", name="soda")


def test_range_to():
    _assert_parsed(parse("1/2 to 3/4 oz simple syrup"),
                   amount=0.5, amount_max=0.75, unit="oz", name="simple syrup")


def test_range_dash():
    _assert_parsed(parse("1-2 oz vodka"), amount=1.0, amount_max=2.0, unit="oz", name="vodka")


def test_name_lowercased_whitespace_collapsed():
    _assert_parsed(parse("  2  oz   GIN  "), amount=2.0, unit="oz", name="gin")


def test_unknown_unit_abstains():
    """If the unit token isn't in the table, qty_unit must abstain."""
    r = parse("1 squeeze fresh lime juice")
    assert r.parse_status == "unparseable"


def test_qty_with_no_unit_abstains():
    r = parse("3 fresh basil leaves")  # 'leaves' is count_noun, not unit; that's task 14
    assert r.parser_rule != "qty_unit"


def test_empty_name_after_qty_unit_abstains():
    r = parse("2 oz")
    assert r.parse_status == "unparseable"
