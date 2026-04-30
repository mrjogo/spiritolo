from ingredients.dedup.audit import (
    audit_name_divergence_within_cluster,
    audit_same_canonical_across_clusters,
    audit_underspecified_ingredients,
    audit_high_in_stack_diversity,
    audit_singleton_editorial_names,
    run_all_audits,
)


def test_audit_singleton_editorial_names_flags_best_perfect_ultimate(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version,
                             cluster_id, dedup_version)
        values
            (6001, 'http://x/best', 'punch', 'Best Negroni Recipe', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1',
             null, 'v1')
        on conflict (source_url) do nothing
    """)

    rows = audit_singleton_editorial_names(db_conn)
    assert any("best" in (r.get("name") or "").lower() for r in rows)


def test_run_all_audits_returns_dict_keyed_by_signal_name(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    summary = run_all_audits(db_conn)
    assert "name_divergence_within_cluster" in summary
    assert "same_canonical_across_clusters" in summary
    assert "underspecified_ingredients" in summary
    assert "high_in_stack_diversity" in summary
    assert "singleton_editorial_names" in summary
