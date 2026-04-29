from ingredients.dedup.normalizer import run_phase1
from ingredients.dedup.version import NORMALIZER_VERSION


def test_phase1_resolves_alias_and_lexical_pending_for_unknown(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at) values
            (3001, 'http://x/a', 'punch', 'The Negroni',          '{}'::jsonb, now()),
            (3002, 'http://x/b', 'punch', 'Best Old Fashioned',   '{}'::jsonb, now()),
            (3003, 'http://x/c', 'punch', 'Whiskey Sours',         '{}'::jsonb, now()),
            (3004, 'http://x/d', 'punch', 'Some Wild House Drink','{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    counts = run_phase1(db_conn)
    assert counts["alias"] >= 2     # 'negroni' and 'old fashioned' fixture aliases
    assert counts["lexical"] >= 1   # 'whiskey sours' close-match to 'whiskey sour'
    assert counts["pending_llm"] >= 1  # 'some wild house drink' has no match

    rows = db_conn.execute(
        "select id, canonical_name, canonical_name_source from recipes where id in (3001,3002,3003,3004) order by id"
    ).fetchall()
    statuses = {r[0]: (r[1], r[2]) for r in rows}
    assert statuses[3001] == ("negroni", "alias")
    assert statuses[3002] == ("old fashioned", "alias")
    assert statuses[3003] == ("whiskey sour", "lexical")
    assert statuses[3004] == (None, "pending_llm")


def test_phase1_idempotent_at_current_version(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values (3101, 'http://x/idemp', 'punch', 'The Negroni', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    counts1 = run_phase1(db_conn)
    counts2 = run_phase1(db_conn)
    # Second run touches nothing (already at current version)
    assert sum(counts2.values()) == 0
