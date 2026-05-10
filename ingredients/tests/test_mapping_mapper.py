import psycopg

from ingredients.mapping.mapper import MAPPER_VERSION, run_phase1


def _seed_two_recipes(conn: psycopg.Connection) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/a', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    rows = [
        (rid, 0, "2 oz gin",           "gin"),                  # alias hit
        (rid, 1, "1 oz lemon juicee",  "lemon juicee"),         # lexical hit (typo)
        (rid, 2, "0.5 oz weird thing", "totally weird thing"),  # pending_llm
    ]
    for rid_, pos, raw, name in rows:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid_, pos, raw, name),
        )
    conn.commit()


def test_phase1_resolves_alias_lexical_and_marks_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_two_recipes(conn)
    summary = run_phase1(conn)
    rows = conn.execute(
        "select lower(trim(name)), taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients order by position"
    ).fetchall()
    assert rows == [
        ("gin",                  ids["gin"],         "alias",       MAPPER_VERSION),
        ("lemon juicee",         ids["lemon-juice"], "lexical",     MAPPER_VERSION),
        ("totally weird thing",  None,               "pending_llm", MAPPER_VERSION),
    ]
    assert summary == {"alias": 1, "lexical": 1, "pending_llm": 1}


def test_phase1_is_idempotent(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_two_recipes(conn)
    run_phase1(conn)
    second = run_phase1(conn)
    # Already at current version; nothing in scope.
    assert second == {"alias": 0, "lexical": 0, "pending_llm": 0}
