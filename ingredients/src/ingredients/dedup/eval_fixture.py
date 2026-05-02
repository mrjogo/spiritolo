"""In-memory dedup fixture: small taxonomy + antichain markers + cocktail
aliases. Loaded into TEST_DB_URL by tests via seed_dedup_fixture(conn).

Returns a slug→id dict for tests to look up node_ids by name.

Mirrors mapping/eval_fixture.py shape. Adds antichain-related columns
that mapping/eval_fixture didn't need.
"""

from __future__ import annotations

import psycopg

# Each tuple: (slug, display_name, node_kind, is_cluster_node, default_role,
#              is_defining_garnish, parent_slug_or_None)
_NODES = [
    # Spirit families (parents — not antichain)
    ("whiskey", "Whiskey", None, False, None, False, None),
    ("gin", "Gin", None, False, None, False, None),
    ("rum", "Rum", None, False, None, False, None),
    ("vermouth", "Vermouth", None, False, None, False, None),
    ("amaro", "Amaro", None, False, None, False, None),
    ("bitters", "Bitters", None, False, None, False, None),
    # Whiskey subtypes (antichain)
    ("bourbon", "Bourbon", None, True, "base_spirit", False, "whiskey"),
    ("rye_whiskey", "Rye Whiskey", None, True, "base_spirit", False, "whiskey"),
    # Gin sub-styles (antichain)
    ("london_dry_gin", "London Dry Gin", None, True, "base_spirit", False, "gin"),
    ("old_tom_gin", "Old Tom Gin", None, True, "base_spirit", False, "gin"),
    # Rum subtypes
    ("white_rum", "White Rum", None, True, "base_spirit", False, "rum"),
    # Vermouth subtypes (antichain)
    ("sweet_vermouth", "Sweet Vermouth", None, True, "modifier", False, "vermouth"),
    ("dry_vermouth", "Dry Vermouth", None, True, "modifier", False, "vermouth"),
    # Amari (antichain — substance-modeled)
    ("campari", "Campari", None, True, "modifier", False, "amaro"),
    ("aperol", "Aperol", None, True, "modifier", False, "amaro"),
    # Bitters (antichain — substance-modeled)
    ("angostura_bitters", "Angostura Bitters", None, True, "bitters", False, "bitters"),
    ("peychauds_bitters", "Peychaud's Bitters", None, True, "bitters", False, "bitters"),
    ("orange_bitters", "Orange Bitters", None, True, "bitters", False, "bitters"),
    # Citrus juices (antichain)
    ("lemon_juice", "Lemon Juice", None, True, "citrus", False, None),
    ("lime_juice", "Lime Juice", None, True, "citrus", False, None),
    # Sweeteners
    ("simple_syrup", "Simple Syrup", None, True, "sweetener", False, None),
    # Dilution + ice
    ("soda_water", "Soda Water", None, True, "dilution", False, None),
    ("ice", "Ice", None, True, "ice", False, None),
    # Garnish: one defining (cocktail_onion), one stylistic (lemon_twist)
    ("cocktail_onion", "Cocktail Onion", None, True, "garnish", True, None),
    ("lemon_twist", "Lemon Twist", None, False, "garnish", False, None),
    # Brand-level (NOT antichain)
    ("tanqueray", "Tanqueray", "brand", False, None, False, "london_dry_gin"),
    ("bombay_sapphire", "Bombay Sapphire", "brand", False, None, False, "london_dry_gin"),
]

_ALIASES_TAX = [
    ("rye", "rye_whiskey"),
    ("bourbon whiskey", "bourbon"),
    ("london dry", "london_dry_gin"),
    ("rosso vermouth", "sweet_vermouth"),
    ("italian vermouth", "sweet_vermouth"),
    ("french vermouth", "dry_vermouth"),
    ("angostura", "angostura_bitters"),
    ("peychauds", "peychauds_bitters"),
    ("peychaud's", "peychauds_bitters"),
]

_COCKTAIL_ALIASES = [
    # canonical → list of aliases (each is post-normalize_cocktail_name form)
    ("negroni", ["negroni"]),
    ("old fashioned", ["old fashioned", "old-fashioned", "rye old fashioned"]),
    ("manhattan", ["manhattan"]),
    ("daiquiri", ["daiquiri", "daquiri"]),  # the typo is a useful seed
    ("martini", ["martini"]),
    ("gimlet", ["gimlet"]),
    ("whiskey sour", ["whiskey sour"]),
    ("tom collins", ["tom collins"]),
    ("aperol negroni", ["aperol negroni"]),
    ("white negroni", ["white negroni"]),
    ("hemingway daiquiri", ["hemingway daiquiri"]),
]


def seed_dedup_fixture(conn: psycopg.Connection) -> dict[str, int]:
    """Insert the fixture taxonomy + cocktail aliases. Idempotent: ON
    CONFLICT clauses make it safe to call multiple times in a session.

    Returns slug -> node_id mapping for the inserted/existing nodes.
    """
    ids: dict[str, int] = {}
    for slug, display, node_kind, is_cluster, default_role, def_garnish, _parent in _NODES:
        row = conn.execute(
            """
            insert into taxonomy_nodes
                (slug, display_name, node_kind, is_cluster_node, default_role,
                 is_defining_garnish)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (slug) do update
                set is_cluster_node = excluded.is_cluster_node,
                    default_role    = excluded.default_role,
                    is_defining_garnish = excluded.is_defining_garnish
            returning id
            """,
            (slug, display, node_kind, is_cluster, default_role, def_garnish),
        ).fetchone()
        ids[slug] = row[0]

    for slug, display, node_kind, is_cluster, default_role, def_garnish, parent in _NODES:
        if parent is None:
            continue
        conn.execute(
            """
            insert into taxonomy_edges (parent_id, child_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (ids[parent], ids[slug]),
        )

    for alias, slug in _ALIASES_TAX:
        conn.execute(
            """
            insert into taxonomy_aliases (alias, node_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (alias, ids[slug]),
        )

    for canonical, aliases in _COCKTAIL_ALIASES:
        for a in aliases:
            conn.execute(
                """
                insert into cocktail_aliases (alias, canonical_name, source)
                values (%s, %s, 'seed')
                on conflict do nothing
                """,
                (a, canonical),
            )
    conn.commit()
    return ids
