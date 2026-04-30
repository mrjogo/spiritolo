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


def test_run_worker_stops_after_interrupt(isolated_db, monkeypatch):
    """First Ctrl-C lets the in-flight per-recipe parse + write finish, then
    the loop exits before processing the next recipe."""
    import os
    import signal
    from unittest.mock import patch
    import argparse
    from ingredients import cli as cli_mod

    isolated_db.conn.execute("""
        insert into recipes (id, source_url, site, jsonld, fetched_at) values
            (7001, 'http://x/w1', 'punch', '{"recipeIngredient": ["1 oz gin"]}'::jsonb, now()),
            (7002, 'http://x/w2', 'punch', '{"recipeIngredient": ["1 oz gin"]}'::jsonb, now()),
            (7003, 'http://x/w3', 'punch', '{"recipeIngredient": ["1 oz gin"]}'::jsonb, now())
    """)
    isolated_db.conn.commit()

    calls = [0]
    real_build = cli_mod.build_rows_for_recipe
    def interrupting_build(*args, **kwargs):
        calls[0] += 1
        result = real_build(*args, **kwargs)
        if calls[0] == 1:
            os.kill(os.getpid(), signal.SIGINT)
        return result
    monkeypatch.setattr(cli_mod, "build_rows_for_recipe", interrupting_build)

    args = argparse.Namespace(
        review=False, site=None, limit=None, dry_run=False,
        reset=False, except_version=None, older_than=None, yes=False,
    )
    # Reuse isolated_db's connection; suppress close so the fixture can clean up.
    isolated_db_close = isolated_db.close
    isolated_db.close = lambda: None
    try:
        with patch("ingredients.cli.IngredientsDatabase", return_value=isolated_db):
            cli_mod.run_worker(args)
    finally:
        isolated_db.close = isolated_db_close

    assert calls[0] == 1, (
        f"expected loop to break after first recipe; got {calls[0]} build calls"
    )


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
