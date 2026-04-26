from ingredients.worker import build_rows_for_recipe


def test_build_rows_skips_non_string_entries():
    rows = build_rows_for_recipe(["2 oz gin", None, 5, "1 oz lime"])
    assert [r["raw_text"] for r in rows] == ["2 oz gin", "1 oz lime"]
    assert [r["position"] for r in rows] == [0, 3]


def test_build_rows_records_unparseable():
    rows = build_rows_for_recipe(["¯\\_(ツ)_/¯"])
    assert len(rows) == 1
    r = rows[0]
    assert r["parse_status"] == "unparseable"
    assert r["amount"] is None
    assert r["unit"] is None
    assert r["name"] is None
    assert r["raw_text"] == "¯\\_(ツ)_/¯"


def test_build_rows_parsed_payload_shape():
    rows = build_rows_for_recipe(["2 oz gin"])
    assert len(rows) == 1
    r = rows[0]
    assert r["position"] == 0
    assert r["raw_text"] == "2 oz gin"
    assert r["amount"] == 2.0
    assert r["amount_max"] is None
    assert r["unit"] == "oz"
    assert r["name"] == "gin"
    assert r["modifier"] is None
    assert r["parse_status"] == "parsed"
    assert r["parser_rule"] == "qty_unit"
