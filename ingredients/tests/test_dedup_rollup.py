from ingredients.dedup.rollup import roll_up_to_antichain


def test_brand_rolls_up_to_substance_antichain(dedup_fixture):
    conn, ids = dedup_fixture
    # tanqueray (brand) rolls up to london-dry-gin (cluster_node)
    result = roll_up_to_antichain(conn, ids["tanqueray"])
    assert result == ids["london-dry-gin"]


def test_antichain_node_rolls_up_to_itself(dedup_fixture):
    conn, ids = dedup_fixture
    result = roll_up_to_antichain(conn, ids["campari"])
    assert result == ids["campari"]


def test_node_above_antichain_rolls_up_to_itself(dedup_fixture):
    conn, ids = dedup_fixture
    # 'gin' is above the cut (london-dry-gin / old-tom-gin are antichain).
    # No antichain ancestor exists → returns the node itself.
    result = roll_up_to_antichain(conn, ids["gin"])
    assert result == ids["gin"]


def test_unknown_node_id_returns_input(dedup_fixture):
    conn, _ = dedup_fixture
    result = roll_up_to_antichain(conn, 99_999_999)
    assert result == 99_999_999


def test_multi_parent_picks_first_antichain_ancestor(dedup_fixture):
    conn, ids = dedup_fixture
    # All fixture brands have a single parent that is antichain. Test
    # that the rollup is stable across multiple invocations.
    a = roll_up_to_antichain(conn, ids["tanqueray"])
    b = roll_up_to_antichain(conn, ids["tanqueray"])
    assert a == b == ids["london-dry-gin"]
