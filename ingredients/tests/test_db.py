# DB-integration tests use the `isolated_db` fixture defined in conftest.py,
# which routes through TEST_DB_URL (a *separate* DB from SUPABASE_DB_URL) and
# auto-applies migrations on session start. Tests skip cleanly when
# TEST_DB_URL is unset.

PARSER_VERSION_TEST = "v-test"


def _seed_recipe(db, *, source_url, site, jsonld):
    import json
    db.conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values (%s, %s, %s, %s::jsonb, '2026-04-25T00:00:00Z')
        returning id
        """,
        (source_url, site, "test", json.dumps(jsonld)),
    )
    db.conn.commit()
    return db.conn.execute(
        "select id from recipes where source_url = %s", (source_url,)
    ).fetchone()[0]


def test_work_queue_returns_recipes_lacking_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r1", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin", "1 oz lime"]})

    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid
    assert queue[0]["site"] == "punch"
    assert queue[0]["recipe_ingredient"] == ["2 oz gin", "1 oz lime"]


def test_work_queue_skips_recipes_with_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r2", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert queue == []


def test_work_queue_returns_recipe_with_old_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r3", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid


def test_write_replaces_existing_rows_for_recipe(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r4", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "old", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "old", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "new", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "new", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    rows = db.conn.execute(
        "select raw_text, parser_version from recipe_ingredients where recipe_id = %s",
        (rid,),
    ).fetchall()
    assert rows == [("new", PARSER_VERSION_TEST)]


def test_write_preserves_row_ids_across_reparse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/preserve", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "old", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "gin", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    first_id = db.conn.execute(
        "select id from recipe_ingredients where recipe_id = %s and position = 0",
        (rid,),
    ).fetchone()[0]
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "new", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "gin", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    second_id = db.conn.execute(
        "select id from recipe_ingredients where recipe_id = %s and position = 0",
        (rid,),
    ).fetchone()[0]
    assert first_id == second_id


def test_write_preserves_mapper_fields_when_name_unchanged(isolated_db):
    db = isolated_db
    node_id = db.conn.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('test-gin', 'Test Gin') returning id"
    ).fetchone()[0]
    db.conn.commit()
    rid = _seed_recipe(db, source_url="https://example.com/mapper-keep", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "gin", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    db.conn.execute(
        "update recipe_ingredients set taxonomy_node_id = %s, "
        "mapper_source = 'alias', mapper_version = 'm-test', mapper_at = now(), "
        "role = 'base_spirit', role_source = 'rule' "
        "where recipe_id = %s",
        (node_id, rid),
    )
    db.conn.commit()
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz dry gin", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "gin", "modifier": "dry",
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    row = db.conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version, role, role_source, raw_text "
        "from recipe_ingredients where recipe_id = %s and position = 0",
        (rid,),
    ).fetchone()
    assert row == (node_id, "alias", "m-test", "base_spirit", "rule", "2 oz dry gin")


def test_write_clears_mapper_fields_when_name_changes(isolated_db):
    db = isolated_db
    node_id = db.conn.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('test-vodka-source', 'Test Vodka') returning id"
    ).fetchone()[0]
    db.conn.commit()
    rid = _seed_recipe(db, source_url="https://example.com/mapper-clear", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "gin", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    db.conn.execute(
        "update recipe_ingredients set taxonomy_node_id = %s, "
        "mapper_source = 'alias', mapper_version = 'm-test', mapper_at = now(), "
        "role = 'base_spirit', role_source = 'rule' "
        "where recipe_id = %s",
        (node_id, rid),
    )
    db.conn.commit()
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz vodka", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "vodka", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    row = db.conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version, mapper_at, role, role_source "
        "from recipe_ingredients where recipe_id = %s and position = 0",
        (rid,),
    ).fetchone()
    assert row == (None, None, None, None, None, None)


def test_write_deletes_rows_no_longer_in_new_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/shrink", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin", "1 oz vermouth"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[
            {"position": 0, "raw_text": "2 oz gin", "amount": 2.0, "amount_max": None,
             "unit": "oz", "name": "gin", "modifier": None,
             "parse_status": "parsed", "parser_rule": "qty_unit"},
            {"position": 1, "raw_text": "1 oz vermouth", "amount": 1.0, "amount_max": None,
             "unit": "oz", "name": "vermouth", "modifier": None,
             "parse_status": "parsed", "parser_rule": "qty_unit"},
        ],
        parser_version="v0",
    )
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[
            {"position": 0, "raw_text": "2 oz gin", "amount": 2.0, "amount_max": None,
             "unit": "oz", "name": "gin", "modifier": None,
             "parse_status": "parsed", "parser_rule": "qty_unit"},
        ],
        parser_version=PARSER_VERSION_TEST,
    )
    rows = db.conn.execute(
        "select position from recipe_ingredients where recipe_id = %s order by position",
        (rid,),
    ).fetchall()
    assert rows == [(0,)]


def test_count_eval_rows_filters(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r5", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    assert db.count_eval_rows(site=None, except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="punch", except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="liquor", except_version=None, older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v0", older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v1", older_than=None) == 1


def test_clear_eval_rows_returns_deleted_count(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r6", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    n = db.clear_eval_rows(site=None, except_version=None, older_than=None)
    assert n == 1
