"""One-shot post-D substance promotion.

D's mapper auto-creates node_kind='brand' or node_kind='expression' nodes
for strings that aren't in the seed. Some of those strings are
commercially-branded *but functionally definitional* substances (Campari,
Aperol, Angostura, Peychaud's, etc.). E's antichain modeling expects them
as node_kind=NULL substance nodes, with is_cluster_node=true.

This module:
  - Holds the curator-reviewed allowlist of substance names.
  - Finds auto-created nodes matching the allowlist.
  - Promotes each (interactively in the CLI; programmatically via promote_node).

Auto-created brand nodes already have the right node_id (recipe_ingredients
rows reference them); no row updates are needed. Only node_kind +
is_cluster_node + default_role + a provenance log entry change.
"""

from __future__ import annotations

import psycopg

# Hand-curated. Add to this list when a new substance turns out to need
# promotion. Each name is matched case-insensitively against
# taxonomy_nodes.display_name.
DEFINITIONAL_SUBSTANCES: list[tuple[str, str]] = [
    # (display_name_lower, default_role)
    ("campari",            "modifier"),
    ("aperol",             "modifier"),
    ("amaro montenegro",   "modifier"),
    ("amaro nonino",       "modifier"),
    ("fernet branca",      "modifier"),
    ("fernet-branca",      "modifier"),
    ("cynar",              "modifier"),
    ("chartreuse",         "modifier"),
    ("green chartreuse",   "modifier"),
    ("yellow chartreuse",  "modifier"),
    ("benedictine",        "modifier"),
    ("bénédictine",        "modifier"),
    ("drambuie",           "modifier"),
    ("pimm's",             "modifier"),
    ("pimms",              "modifier"),
    ("suze",               "modifier"),
    ("angostura",          "bitters"),
    ("angostura bitters",  "bitters"),
    ("peychaud's",         "bitters"),
    ("peychauds",          "bitters"),
    ("peychaud's bitters", "bitters"),
]


def candidate_promotions(conn: psycopg.Connection) -> list[dict]:
    """Return auto-created nodes whose display_name matches an allowlist
    entry AND whose current node_kind is brand/expression."""
    names_lc = [n for n, _ in DEFINITIONAL_SUBSTANCES]
    rows = conn.execute(
        """
        select n.id, n.slug, n.display_name, n.node_kind, p.raw_string, p.source
        from taxonomy_nodes n
        left join taxonomy_provenance p on p.node_id = n.id
        where n.node_kind in ('brand', 'expression')
          and lower(n.display_name) = any(%s)
        order by n.display_name
        """,
        (names_lc,),
    ).fetchall()
    default_role_by_name = {
        n.lower(): dr for n, dr in DEFINITIONAL_SUBSTANCES
    }
    return [
        {
            "id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "current_node_kind": r[3],
            "provenance_raw_string": r[4],
            "provenance_source": r[5],
            "proposed_default_role": default_role_by_name.get(r[2].lower()),
        }
        for r in rows
    ]


def promote_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    default_role: str,
    promoter: str = "operator",
) -> None:
    """Set node_kind=NULL, is_cluster_node=true, default_role=<default_role>.
    Logs the promotion in taxonomy_provenance for audit (using source='manual')."""
    conn.execute(
        """
        update taxonomy_nodes
           set node_kind = null,
               is_cluster_node = true,
               default_role = %s
         where slug = %s
        """,
        (default_role, slug),
    )
    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, model_id)
        select id, 'manual', 'v1', %s, %s
        from taxonomy_nodes
        where slug = %s
        on conflict (node_id) do update
            set source = 'manual',
                raw_string = excluded.raw_string,
                model_id = excluded.model_id
        """,
        (f"promoted by {promoter}", "substance-promotion", slug),
    )
    conn.commit()
