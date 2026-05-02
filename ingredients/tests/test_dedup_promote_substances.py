from ingredients.dedup.promote_substances import (
    DEFINITIONAL_SUBSTANCES,
    candidate_promotions,
    promote_node,
)


def test_definitional_substances_includes_expected_names():
    expected = {
        "campari", "aperol", "fernet branca", "angostura",
        "peychaud's", "chartreuse", "cynar", "suze",
        "benedictine", "drambuie", "pimm's", "amaro montenegro",
    }
    seen = {s.lower() for s in [name for name, _ in DEFINITIONAL_SUBSTANCES]}
    missing = expected - seen
    assert not missing, f"DEFINITIONAL_SUBSTANCES missing: {missing}"


def test_candidate_promotions_finds_auto_created_brands(dedup_fixture, db_conn):
    """Insert an auto-created 'campari' brand node (as if D's mapper made
    it before E's promote-substances run); the candidate query must find it."""
    conn, ids = dedup_fixture
    db_conn.execute("""
        update taxonomy_nodes
           set node_kind = 'brand', is_cluster_node = false, default_role = null
         where slug = 'campari'
    """)
    db_conn.execute("""
        insert into taxonomy_provenance (node_id, source, mapper_version, raw_string, model_id)
        values ((select id from taxonomy_nodes where slug = 'campari'),
                'llm-mapper', 'v1', 'Campari', 'claude-haiku-4-5')
        on conflict (node_id) do update set source = 'llm-mapper'
    """)

    cands = candidate_promotions(db_conn)
    slugs = {c["slug"] for c in cands}
    assert "campari" in slugs


def test_promote_node_sets_node_kind_null_and_is_cluster_node_true(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        update taxonomy_nodes
           set node_kind = 'brand', is_cluster_node = false, default_role = null
         where slug = 'campari'
    """)

    promote_node(
        db_conn, slug="campari",
        default_role="modifier",
        promoter="test-suite",
    )

    row = db_conn.execute(
        "select node_kind, is_cluster_node, default_role from taxonomy_nodes where slug = 'campari'"
    ).fetchone()
    assert row == (None, True, "modifier")
