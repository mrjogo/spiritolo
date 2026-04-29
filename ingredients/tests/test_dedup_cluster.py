import pytest

from ingredients.dedup.cluster import (
    INCLUDED_ROLES,
    compute_cluster_key,
    compute_variant_key,
    in_cluster_key,
)


def _ing(role, antichain_node_id=1, taxonomy_node_id=1, amount=1.0,
         amount_max=None, unit="oz", is_defining_garnish=False):
    return {
        "role": role,
        "antichain_node_id": antichain_node_id,
        "taxonomy_node_id": taxonomy_node_id,
        "amount": amount,
        "amount_max": amount_max,
        "unit": unit,
        "is_defining_garnish": is_defining_garnish,
    }


def test_in_cluster_key_includes_default_roles():
    for role in INCLUDED_ROLES:
        assert in_cluster_key(_ing(role=role))


def test_in_cluster_key_excludes_ice():
    assert not in_cluster_key(_ing(role="ice"))


def test_in_cluster_key_garnish_uses_defining_flag():
    assert not in_cluster_key(_ing(role="garnish", is_defining_garnish=False))
    assert     in_cluster_key(_ing(role="garnish", is_defining_garnish=True))


def test_in_cluster_key_unknown_role_excluded_by_default():
    assert not in_cluster_key(_ing(role="high_abv"))


def test_compute_cluster_key_independent_of_ingredient_ordering():
    ings1 = [_ing(role="base_spirit", antichain_node_id=1),
             _ing(role="modifier",    antichain_node_id=2)]
    ings2 = [_ing(role="modifier",    antichain_node_id=2),
             _ing(role="base_spirit", antichain_node_id=1)]
    assert compute_cluster_key("negroni", ings1) == compute_cluster_key("negroni", ings2)


def test_compute_cluster_key_independent_of_amount():
    a = [_ing(role="base_spirit", antichain_node_id=1, amount=1.0)]
    b = [_ing(role="base_spirit", antichain_node_id=1, amount=2.0)]
    assert compute_cluster_key("negroni", a) == compute_cluster_key("negroni", b)


def test_compute_variant_key_distinguishes_amounts():
    a = [_ing(role="base_spirit", antichain_node_id=1, amount=1.0, unit="oz")]
    b = [_ing(role="base_spirit", antichain_node_id=1, amount=2.0, unit="oz")]
    ck_a = compute_cluster_key("negroni", a)
    ck_b = compute_cluster_key("negroni", b)
    assert ck_a == ck_b
    assert compute_variant_key(ck_a, a) != compute_variant_key(ck_b, b)


def test_compute_variant_key_distinguishes_brand():
    base = _ing(role="base_spirit", antichain_node_id=1, taxonomy_node_id=1)
    branded = {**base, "taxonomy_node_id": 42}
    ck = compute_cluster_key("negroni", [base])
    assert compute_variant_key(ck, [base]) != compute_variant_key(ck, [branded])


def test_compute_cluster_key_excludes_ice():
    no_ice = [_ing(role="base_spirit", antichain_node_id=1)]
    with_ice = no_ice + [_ing(role="ice", antichain_node_id=99)]
    assert compute_cluster_key("negroni", no_ice) == compute_cluster_key("negroni", with_ice)


# === Integration tests (require dedup_fixture + db_conn) ===

def test_run_cluster_compute_groups_identical_negronis(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5001, 'http://x/n1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5002, 'http://x/n2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    for rid in (5001, 5002):
        for pos, slug, amount in (
            (1, "london_dry_gin",  1.0),
            (2, "campari",         1.0),
            (3, "sweet_vermouth",  1.0),
        ):
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))

    from ingredients.dedup.cluster import run_cluster_compute
    counts = run_cluster_compute(db_conn)
    assert counts["recipes_clustered"] == 2

    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5001, 5002)"
    ).fetchall()
    assert rows[0][0] == rows[1][0]
    assert rows[0][1] == rows[1][1]


def test_run_cluster_compute_separates_ratio_variants(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5101, 'http://x/r1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5102, 'http://x/r2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    for rid, gin_amt in ((5101, 1.0), (5102, 1.5)):
        for pos, slug, amount in (
            (1, "london_dry_gin",  gin_amt),
            (2, "campari",         1.0),
            (3, "sweet_vermouth",  1.0),
        ):
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))

    from ingredients.dedup.cluster import run_cluster_compute
    run_cluster_compute(db_conn)

    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5101, 5102)"
    ).fetchall()
    assert rows[0][0] == rows[1][0]
    assert rows[0][1] != rows[1][1]


def test_run_cluster_compute_ignores_ice(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5201, 'http://x/i1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5202, 'http://x/i2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    base = [
        (1, "london_dry_gin", 1.0),
        (2, "campari",        1.0),
        (3, "sweet_vermouth", 1.0),
    ]
    for rid, ings in ((5201, base), (5202, base + [(4, "ice", 1.0)])):
        for pos, slug, amount in ings:
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))

    from ingredients.dedup.cluster import run_cluster_compute
    run_cluster_compute(db_conn)
    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5201, 5202)"
    ).fetchall()
    assert rows[0] == rows[1]
