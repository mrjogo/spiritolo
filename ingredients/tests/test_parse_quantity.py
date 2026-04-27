from ingredients.parser import parse_quantity


def test_integer():
    assert parse_quantity("3 oz gin") == (3.0, None, 1)


def test_decimal():
    assert parse_quantity("0.25 cup honey") == (0.25, None, 4)
    assert parse_quantity("1.5 oz") == (1.5, None, 3)


def test_fraction():
    assert parse_quantity("1/2 oz") == (0.5, None, 3)
    assert parse_quantity("3/4 oz") == (0.75, None, 3)


def test_mixed_number():
    assert parse_quantity("1 1/2 oz gin") == (1.5, None, 5)
    assert parse_quantity("2 3/4 cups") == (2.75, None, 5)


def test_range_with_to():
    assert parse_quantity("1/2 to 3/4 oz") == (0.5, 0.75, 10)
    assert parse_quantity("1 to 2 oz") == (1.0, 2.0, 6)


def test_range_with_dash():
    """Some sites write '1-2 oz' instead of '1 to 2 oz'. Treat as range."""
    assert parse_quantity("1-2 oz") == (1.0, 2.0, 3)


def test_no_quantity_prefix_returns_none():
    assert parse_quantity("Garnish: lemon twist") is None
    assert parse_quantity("ice") is None
    assert parse_quantity("") is None
    assert parse_quantity("oz gin") is None


def test_quantity_with_no_following_text():
    """A quantity at end of string still parses; consumer decides if useful."""
    assert parse_quantity("2") == (2.0, None, 1)
    assert parse_quantity("1/2") == (0.5, None, 3)
