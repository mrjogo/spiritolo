"""Smoke test for the dedup eval fixture. Real exercise happens in the
layer/orchestrator tests that consume it."""

from ingredients.dedup.eval_fixture import seed_dedup_fixture


def test_seed_dedup_fixture_creates_taxonomy_and_aliases(db_conn):
    ids = seed_dedup_fixture(db_conn)

    assert "gin" in ids
    assert "london-dry-gin" in ids
    assert "campari" in ids
    assert "sweet-vermouth" in ids
    assert "angostura-bitters" in ids
    assert "lemon-juice" in ids
    assert "ice" in ids

    # Antichain markers
    cluster_nodes = {
        row[0] for row in db_conn.execute(
            "select slug from taxonomy_nodes where is_cluster_node = true"
        ).fetchall()
    }
    assert "london-dry-gin" in cluster_nodes
    assert "campari" in cluster_nodes
    assert "sweet-vermouth" in cluster_nodes
    assert "bourbon" in cluster_nodes
    assert "rye-whiskey" in cluster_nodes
    assert "gin" not in cluster_nodes  # navigation parent, not antichain

    # default_role
    default_roles = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select slug, default_role from taxonomy_nodes where default_role is not null"
        ).fetchall()
    }
    assert default_roles.get("london-dry-gin") == "base_spirit"
    assert default_roles.get("campari") == "modifier"
    assert default_roles.get("sweet-vermouth") == "modifier"
    assert default_roles.get("angostura-bitters") == "bitters"
    assert default_roles.get("lemon-juice") == "citrus"
    assert default_roles.get("simple-syrup") == "sweetener"
    assert default_roles.get("soda-water") == "dilution"
    assert default_roles.get("ice") == "ice"

    # Cocktail aliases seeded
    aliases = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select alias, canonical_name from cocktail_aliases"
        ).fetchall()
    }
    assert aliases.get("negroni") == "negroni"
    assert aliases.get("old fashioned") == "old fashioned"
    assert aliases.get("manhattan") == "manhattan"
