"""A minimal taxonomy that exercises every Phase 1/Phase 2 path in tests.

Layout (relevant for cascade coverage):

    citrus
      └── lemon
            ├── lemon_juice    [alias: 'lemon juice']
            └── lemon_wheel
    gin                        [alias: 'gin', 'london dry gin']
      └── london_dry_gin
            └── tanqueray      (role=brand, alias: 'tanqueray', 'tanqueray gin')
    bourbon                    [alias: 'bourbon']

Tests assert mapper outcomes against this fixture rather than the
production seed, so eval results don't drift as the seed grows.
"""

from __future__ import annotations

import psycopg


def seed(conn: psycopg.Connection) -> dict[str, int]:
    """Wipe taxonomy_* tables and load the fixture. Returns slug -> id."""
    conn.execute("truncate table taxonomy_aliases, taxonomy_edges, taxonomy_nodes restart identity cascade")

    nodes = [
        ("citrus",          "Citrus",          None),
        ("lemon",           "Lemon",           None),
        ("lemon_juice",     "Lemon Juice",     None),
        ("lemon_wheel",     "Lemon Wheel",     None),
        ("gin",             "Gin",             None),
        ("london_dry_gin",  "London Dry Gin",  None),
        ("tanqueray",       "Tanqueray",       "brand"),
        ("bourbon",         "Bourbon",         None),
    ]
    ids: dict[str, int] = {}
    for slug, name, role in nodes:
        row = conn.execute(
            "insert into taxonomy_nodes (slug, display_name, role) "
            "values (%s, %s, %s) returning id",
            (slug, name, role),
        ).fetchone()
        ids[slug] = row[0]

    edges = [
        ("citrus",         "lemon"),
        ("lemon",          "lemon_juice"),
        ("lemon",          "lemon_wheel"),
        ("gin",            "london_dry_gin"),
        ("london_dry_gin", "tanqueray"),
    ]
    for parent, child in edges:
        conn.execute(
            "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
            (ids[parent], ids[child]),
        )

    aliases = [
        ("lemon juice",      "lemon_juice"),
        ("gin",              "gin"),
        ("london dry gin",   "london_dry_gin"),
        ("tanqueray",        "tanqueray"),
        ("tanqueray gin",    "tanqueray"),
        ("bourbon",          "bourbon"),
    ]
    for alias, slug in aliases:
        conn.execute(
            "insert into taxonomy_aliases (alias, node_id) values (%s, %s)",
            (alias, ids[slug]),
        )

    conn.commit()
    return ids
