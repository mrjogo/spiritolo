"""The 9 public-schema tables the uploader pushes from local to staging.

Definitive list and dependency order. Imported by both the uploader and
(later) Stage 3 utilities. Excluded from this list and from the upload:
profiles (excluded from the dump; FKs to auth.users), all views.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class OwnedTable:
    name: str
    pk_columns: tuple[str, ...]
    sequence: str | None  # None for composite-PK tables (no auto-id sequence)


OWNED_TABLES: tuple[OwnedTable, ...] = (
    OwnedTable("recipes", ("id",), "recipes_id_seq"),
    OwnedTable("taxonomy_nodes", ("id",), "taxonomy_nodes_id_seq"),
    OwnedTable("cocktail_aliases", ("alias", "canonical_name"), None),
    OwnedTable("recipe_ingredients", ("id",), "recipe_ingredients_id_seq"),
    OwnedTable("taxonomy_edges", ("parent_id", "child_id"), None),
    OwnedTable("taxonomy_aliases", ("alias", "node_id"), None),
    OwnedTable("taxonomy_provenance", ("node_id",), None),
    OwnedTable("taxonomy_proposals", ("id",), "taxonomy_proposals_id_seq"),
    OwnedTable("recipe_clusters", ("id",), "recipe_clusters_id_seq"),
)
