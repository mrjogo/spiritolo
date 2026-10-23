"""A minimal taxonomy that exercises every Phase 1/Phase 2 path in tests.

Layout (relevant for cascade coverage):

    citrus
      └── lemon
            ├── lemon-juice    [alias: 'lemon juice']
            └── lemon-wheel
    gin                        [alias: 'gin', 'london dry gin']
      └── london-dry-gin
            └── tanqueray      (node_kind=brand, alias: 'tanqueray', 'tanqueray gin')
    bourbon                    [alias: 'bourbon']

Tests assert mapper outcomes against this fixture rather than the
production seed, so eval results don't drift as the seed grows.
"""

from __future__ import annotations

from common.db import Connection


def seed(conn: Connection) -> dict[str, int]:
    """Wipe taxonomy_* tables and load the fixture. Returns slug -> id."""
    with conn.transaction():
        for table in ("taxonomy_aliases", "taxonomy_edges", "taxonomy_provenance", "taxonomy_nodes"):
            conn.execute(f"delete from {table}")

        nodes = [
            ("citrus",          "Citrus",          None),
            ("lemon",           "Lemon",           None),
            ("lemon-juice",     "Lemon Juice",     None),
            ("lemon-wheel",     "Lemon Wheel",     None),
            ("gin",             "Gin",             None),
            ("london-dry-gin",  "London Dry Gin",  None),
            ("tanqueray",       "Tanqueray",       "brand"),
            ("bourbon",         "Bourbon",         None),
        ]
        ids: dict[str, int] = {}
        for slug, name, node_kind in nodes:
            row = conn.execute(
                "insert into taxonomy_nodes (slug, display_name, node_kind) "
                "values (?, ?, ?) returning id",
                (slug, name, node_kind),
            ).fetchone()
            ids[slug] = row[0]

        edges = [
            ("citrus",         "lemon"),
            ("lemon",          "lemon-juice"),
            ("lemon",          "lemon-wheel"),
            ("gin",            "london-dry-gin"),
            ("london-dry-gin", "tanqueray"),
        ]
        for parent, child in edges:
            conn.execute(
                "insert into taxonomy_edges (parent_id, child_id) values (?, ?)",
                (ids[parent], ids[child]),
            )

        aliases = [
            ("lemon juice",      "lemon-juice"),
            ("gin",              "gin"),
            ("london dry gin",   "london-dry-gin"),
            ("tanqueray",        "tanqueray"),
            ("tanqueray gin",    "tanqueray"),
            ("bourbon",          "bourbon"),
        ]
        for alias, slug in aliases:
            conn.execute(
                "insert into taxonomy_aliases (alias, node_id) values (?, ?)",
                (alias, ids[slug]),
            )
    return ids
