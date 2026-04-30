"""End-to-end dedup pipeline test against the fixture.

Inserts three Negroni recipes (two identical, one with different ratios)
plus an Old Fashioned. After running normalize + cluster, asserts cluster
membership + variant grouping.
"""

from ingredients.dedup.cluster import run_cluster_compute
from ingredients.dedup.normalizer import run_phase1


def test_end_to_end_negroni_old_fashioned(dedup_fixture, db_conn):
    conn, ids = dedup_fixture

    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values
            (7001, 'http://x/n1', 'punch',  'Negroni',                  '{}'::jsonb, now()),
            (7002, 'http://x/n2', 'imbibe', 'The Best Negroni Recipe',  '{}'::jsonb, now()),
            (7003, 'http://x/n3', 'serious-eats', 'Negroni',            '{}'::jsonb, now()),
            (7004, 'http://x/of', 'punch',  'Old Fashioned',            '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)

    def add_ingredients(rid, ings):
        for pos, slug, amount, unit in ings:
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, %s, 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, unit, ids[slug]))

    add_ingredients(7001, [
        (1, "london_dry_gin",  1.0, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7002, [
        (1, "london_dry_gin",  1.0, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7003, [
        (1, "london_dry_gin",  1.5, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7004, [
        (1, "bourbon",            2.0, "oz"),
        (2, "simple_syrup",       0.25, "oz"),
        (3, "angostura_bitters",  2.0, "dash"),
    ])

    norm_counts = run_phase1(db_conn)
    assert norm_counts.get("alias", 0) >= 2
    cluster_counts = run_cluster_compute(db_conn)
    assert cluster_counts["recipes_clustered"] == 4

    rows = {
        r[0]: (r[1], r[2])
        for r in db_conn.execute(
            "select id, cluster_id, variant_key from recipes where id in (7001,7002,7003,7004)"
        ).fetchall()
    }
    assert rows[7001][0] == rows[7002][0] == rows[7003][0]
    assert rows[7001][1] == rows[7002][1]
    assert rows[7003][1] != rows[7001][1]
    assert rows[7004][0] != rows[7001][0]

    cluster_rows = db_conn.execute(
        "select id, recipe_count, source_count from recipe_clusters where id in (%s, %s)",
        (rows[7001][0], rows[7004][0]),
    ).fetchall()
    counts_by_id = {r[0]: (r[1], r[2]) for r in cluster_rows}
    assert counts_by_id[rows[7001][0]] == (3, 3)
    assert counts_by_id[rows[7004][0]] == (1, 1)
