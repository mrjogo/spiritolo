"""Smoke test for the dedup eval fixture. Real exercise happens in the
layer/orchestrator tests that consume it."""

from ingredients.dedup.eval_fixture import seed_dedup_fixture


def test_seed_dedup_fixture_creates_taxonomy_and_aliases(db_conn):
    ids = seed_dedup_fixture(db_conn)

    assert "gin" in ids
    assert "london_dry_gin" in ids
    assert "campari" in ids
    assert "sweet_vermouth" in ids
    assert "angostura_bitters" in ids
    assert "lemon_juice" in ids
    assert "ice" in ids

    # Antichain markers
    cluster_nodes = {
        row[0] for row in db_conn.execute(
            "select slug from taxonomy_nodes where is_cluster_node = true"
        ).fetchall()
    }
    assert "london_dry_gin" in cluster_nodes
    assert "campari" in cluster_nodes
    assert "sweet_vermouth" in cluster_nodes
    assert "bourbon" in cluster_nodes
    assert "rye_whiskey" in cluster_nodes
    assert "gin" not in cluster_nodes  # navigation parent, not antichain

    # default_role
    default_roles = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select slug, default_role from taxonomy_nodes where default_role is not null"
        ).fetchall()
    }
    assert default_roles.get("london_dry_gin") == "base_spirit"
    assert default_roles.get("campari") == "modifier"
    assert default_roles.get("sweet_vermouth") == "modifier"
    assert default_roles.get("angostura_bitters") == "bitters"
    assert default_roles.get("lemon_juice") == "citrus"
    assert default_roles.get("simple_syrup") == "sweetener"
    assert default_roles.get("soda_water") == "dilution"
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
