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

    # role_default
    role_defaults = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select slug, role_default from taxonomy_nodes where role_default is not null"
        ).fetchall()
    }
    assert role_defaults.get("london_dry_gin") == "base_spirit"
    assert role_defaults.get("campari") == "modifier"
    assert role_defaults.get("sweet_vermouth") == "modifier"
    assert role_defaults.get("angostura_bitters") == "bitters"
    assert role_defaults.get("lemon_juice") == "citrus"
    assert role_defaults.get("simple_syrup") == "sweetener"
    assert role_defaults.get("soda_water") == "dilution"
    assert role_defaults.get("ice") == "ice"

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
