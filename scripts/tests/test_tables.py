"""Owned-tables registry: shape and invariants."""
from upload_to_staging.tables import OWNED_TABLES, OwnedTable


def test_expected_tables_present():
    names = [t.name for t in OWNED_TABLES]
    assert names == [
        "recipes",
        "taxonomy_nodes",
        "cocktail_aliases",
        "recipe_ingredients",
        "taxonomy_edges",
        "taxonomy_aliases",
        "taxonomy_provenance",
        "taxonomy_proposals",
        "recipe_clusters",
    ]


def test_each_table_has_pk_columns():
    for t in OWNED_TABLES:
        assert isinstance(t.pk_columns, tuple)
        assert len(t.pk_columns) >= 1
        assert all(isinstance(c, str) and c for c in t.pk_columns)


def test_sequence_set_only_for_bigserial_tables():
    by_name = {t.name: t for t in OWNED_TABLES}
    assert by_name["recipes"].sequence == "recipes_id_seq"
    assert by_name["recipe_ingredients"].sequence == "recipe_ingredients_id_seq"
    assert by_name["taxonomy_nodes"].sequence == "taxonomy_nodes_id_seq"
    assert by_name["taxonomy_proposals"].sequence == "taxonomy_proposals_id_seq"
    assert by_name["recipe_clusters"].sequence == "recipe_clusters_id_seq"
    # Composite-PK tables have no sequence
    for name in ("cocktail_aliases", "taxonomy_edges",
                 "taxonomy_aliases", "taxonomy_provenance"):
        assert by_name[name].sequence is None


def test_owned_table_is_immutable_dataclass():
    t = OWNED_TABLES[0]
    import dataclasses
    assert dataclasses.is_dataclass(t)
    assert getattr(type(t), "__dataclass_params__").frozen is True
