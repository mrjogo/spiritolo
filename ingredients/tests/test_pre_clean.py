from ingredients.parser import pre_clean, ParseResult, PARSER_VERSION


def test_parser_version_is_a_nonempty_string():
    assert isinstance(PARSER_VERSION, str)
    assert PARSER_VERSION


def test_pre_clean_unicode_fractions_to_ascii():
    assert pre_clean("½ oz gin") == "1/2 oz gin"
    assert pre_clean("¾ ounce rye") == "3/4 ounce rye"
    assert pre_clean("⅓ cup sugar") == "1/3 cup sugar"


def test_pre_clean_collapses_whitespace():
    assert pre_clean("1   oz   gin") == "1 oz gin"
    assert pre_clean("1\toz\tgin") == "1 oz gin"


def test_pre_clean_strips_outer_whitespace_and_punct():
    assert pre_clean("  1 oz gin  ") == "1 oz gin"
    assert pre_clean("1 oz gin,") == "1 oz gin"
    assert pre_clean("1 oz gin.") == "1 oz gin"


def test_pre_clean_preserves_inner_punct():
    assert pre_clean("1 oz gin (such as Beefeater)") == "1 oz gin (such as Beefeater)"


def test_pre_clean_nfkc_normalizes():
    # U+00A0 (non-breaking space) becomes regular space via NFKC normalization.
    nbsp_input = f"1{chr(0xA0)}oz{chr(0xA0)}gin"
    assert pre_clean(nbsp_input) == "1 oz gin"


def test_parse_result_default_shape():
    r = ParseResult(raw_text="x", parse_status="unparseable")
    assert r.raw_text == "x"
    assert r.parse_status == "unparseable"
    assert r.parser_rule is None
    assert r.amount is None
    assert r.amount_max is None
    assert r.unit is None
    assert r.name is None
    assert r.modifier is None
