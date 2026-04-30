"""DB helpers for E. Each function takes a psycopg conn so tests share
production code paths via TEST_DB_URL."""

from ingredients.dedup.db import (
    fetch_unresolved_recipe_names,
    write_normalization,
    write_pending_normalize,
    write_normalize_abstain,
    add_cocktail_alias,
    fetch_pending_canonical_names,
)
from ingredients.dedup.version import NORMALIZER_VERSION


def test_fetch_unresolved_recipe_names_excludes_already_normalized(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values
            (1001, 'http://x/n1', 'punch', 'The Negroni', '{}'::jsonb, now()),
            (1002, 'http://x/n2', 'punch', 'Daquiri', '{}'::jsonb, now()),
            (1003, 'http://x/n3', 'punch', 'Old Fashioned', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    db_conn.execute("""
        update recipes set canonical_name = 'old fashioned',
                           canonical_name_source = 'alias',
                           normalizer_version = %s, normalized_at = now()
         where id = 1003
    """, (NORMALIZER_VERSION,))
    names = fetch_unresolved_recipe_names(db_conn, normalizer_version=NORMALIZER_VERSION)
    # 1001's raw name is "The Negroni"; 1002's is "Daquiri"; both unresolved.
    assert "The Negroni" in names
    assert "Daquiri" in names
    # 1003 is excluded because it's already at current version
    assert "Old Fashioned" not in names


def test_write_normalization_updates_all_rows_sharing_name(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at) values
            (2001, 'http://x/a', 'punch', 'Negroni', '{}'::jsonb, now()),
            (2002, 'http://x/b', 'imbibe', 'Negroni', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    n = write_normalization(
        db_conn, raw_name="Negroni", normalized="negroni",
        canonical_name="negroni", source="alias",
        normalizer_version=NORMALIZER_VERSION,
    )
    assert n == 2
    canonicals = db_conn.execute(
        "select canonical_name from recipes where id in (2001, 2002)"
    ).fetchall()
    assert all(r[0] == "negroni" for r in canonicals)


def test_add_cocktail_alias_idempotent(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    add_cocktail_alias(db_conn, alias="the best negroni", canonical_name="negroni", source="llm")
    add_cocktail_alias(db_conn, alias="the best negroni", canonical_name="negroni", source="llm")
    rows = db_conn.execute(
        "select count(*) from cocktail_aliases where alias = %s and canonical_name = %s",
        ("the best negroni", "negroni"),
    ).fetchone()
    assert rows[0] == 1


def test_write_pending_normalize_marks_pending(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values (3001, 'http://x/p1', 'punch', 'Some Wild House Drink', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    n = write_pending_normalize(db_conn, raw_name="Some Wild House Drink", normalizer_version=NORMALIZER_VERSION)
    assert n == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source, normalizer_version from recipes where id = 3001"
    ).fetchone()
    assert row == (None, "pending_llm", NORMALIZER_VERSION)


def test_fetch_pending_canonical_names_finds_only_pending_llm(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name_source, normalizer_version)
        values
            (4001, 'http://x/q1', 'punch', 'Pending One', '{}'::jsonb, now(), 'pending_llm', %s),
            (4002, 'http://x/q2', 'punch', 'Pending Two', '{}'::jsonb, now(), 'pending_llm', %s),
            (4003, 'http://x/q3', 'punch', 'Already Resolved', '{}'::jsonb, now(), 'alias', %s)
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION, NORMALIZER_VERSION, NORMALIZER_VERSION))
    db_conn.execute("update recipes set canonical_name = 'foo' where id = 4003")
    names = fetch_pending_canonical_names(db_conn, normalizer_version=NORMALIZER_VERSION)
    assert "Pending One" in names
    assert "Pending Two" in names
    assert "Already Resolved" not in names


def test_write_normalize_abstain_marks_abstain(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name_source, normalizer_version)
        values (5001, 'http://x/ab', 'punch', 'Editorial Junk', '{}'::jsonb, now(), 'pending_llm', %s)
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    n = write_normalize_abstain(db_conn, raw_name="Editorial Junk", normalizer_version=NORMALIZER_VERSION)
    assert n == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 5001"
    ).fetchone()
    assert row == (None, "abstain")
