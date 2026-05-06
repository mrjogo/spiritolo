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


def test_pre_clean_decodes_html_entities():
    # &frasl; (U+2044 fraction slash) → / via the existing slash-replace step.
    assert pre_clean("1&frasl;2 oz gin") == "1/2 oz gin"
    # Numeric entity for fraction slash.
    assert pre_clean("1&#8260;2 oz gin") == "1/2 oz gin"
    # &amp; should not break later steps.
    assert pre_clean("1 oz Smith &amp; Cross rum") == "1 oz Smith & Cross rum"
    # No entities present → unchanged.
    assert pre_clean("1 oz gin") == "1 oz gin"


def test_pre_clean_hanging_hyphen_qty_unit():
    # v9: corpus typo `1- ounce X` (stray space after the dash) normalises.
    assert pre_clean("1- ounce gin") == "1 ounce gin"
    assert pre_clean("1/2- ounce lime juice") == "1/2 ounce lime juice"


def test_pre_clean_hanging_hyphen_range():
    # v9: `2- to 3-inch X` first collapses to `2 to 3 inch X`, then the
    # leading-size-annotation strip drops the qty AND `inch` together
    # (the qty was the size, not a count).
    assert pre_clean("2- to 3-inch cinnamon stick") == "cinnamon stick"
    # `quart` IS a real volume unit, so the range survives the size strip.
    assert pre_clean("4- to 6-quart slow cooker") == "4 to 6 quart slow cooker"


def test_pre_clean_leading_size_annotation_strip():
    # v9: `inch`/`cm`/`mm`/`foot` describe physical size, not row qty;
    # the leading number is the size, so we drop both.
    assert pre_clean("3-inch cinnamon stick") == "cinnamon stick"
    assert pre_clean("1-inch knob fresh ginger") == "knob fresh ginger"
    assert pre_clean("12 1/8-inch-thick slices cucumber") == "slices cucumber"
    # Real volume units are NOT stripped — handled by `_HYPHEN_QTY_UNIT_RE`.
    assert pre_clean("1/2-ounce dry vermouth") == "1/2 ounce dry vermouth"
    # Mid-string `inch` annotation is left alone.
    assert pre_clean("1 750-ml bottle of vodka") == "1 750-ml bottle of vodka"


def test_pre_clean_doubled_unit():
    # v9: `1/2 ounce ounce X` corpus typo strips the duplicate.
    assert pre_clean("1/2 ounce ounce grapefruit syrup") == "1/2 ounce grapefruit syrup"
    assert pre_clean("2 ounces ounces Roger Groult Calvados") == "2 ounces Roger Groult Calvados"
    # Different units (corpus error of a different kind) are NOT collapsed.
    assert pre_clean("1/4 cup ounces gin") == "1/4 cup ounces gin"


def test_pre_clean_range_with_repeated_unit():
    # v9: `3/4 cup to 1 cup X` collapses to `3/4 to 1 cup X`.
    assert pre_clean("3/4 cup to 1 cup orange juice") == "3/4 to 1 cup orange juice"
    assert pre_clean("1/4 ounce to 1/2 ounce vanilla syrup") == "1/4 to 1/2 ounce vanilla syrup"
    # Different canonical units are left alone.
    assert pre_clean("2 tablespoons to 1/4 cup syrup") == "2 tablespoons to 1/4 cup syrup"


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
