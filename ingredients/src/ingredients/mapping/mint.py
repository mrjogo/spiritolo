"""Mechanically mint a provisional taxonomy node for an unresolved name.

`map-ingredient` no longer proposes or auto-creates taxonomy structure via the
LLM. Any ingredient name that survives the alias / lexical / LLM tiers without a
match to an existing node is minted here: a deterministic kebab slug from the
normalized name becomes a ``status='provisional'`` node (no ``node_kind``, no
parent edge, not a cluster node), stamped with a ``map-mint`` provenance row and
a shared ``provisional`` resolution. The later ``combine-nodes`` /
``connect-nodes`` stages merge, place, and promote it to ``live``.

Get-or-create by slug: identical normalized names collapse onto one slug, and if
the slug already names an existing (live) node the resolution simply attaches to
it — no duplicate, no downgrade of the live node. The mint is fully
deterministic and needs no LLM, so it runs even in the CLI cold build where
``providers is None``.
"""

from __future__ import annotations

import psycopg

from ingredients.mapping.resolutions import write_resolution
from ingredients.recipegf.slug import is_valid_slug, slugify


def mint_provisional_node(
    conn: psycopg.Connection,
    *,
    normalized_name: str,
    version: str,
    model_id: str | None = None,
) -> str | None:
    """Get-or-create a node by the name's deterministic slug, resolving to it.

    Returns the slug, or ``None`` when the name cannot produce a valid kebab slug
    (empty / punctuation-only) — the caller abstains rather than minting a bad
    node. Idempotent: the node insert, the provenance insert, and the resolution
    UPSERT all tolerate repeat calls, so re-running map over the same name is a
    no-op. An ``on conflict (slug) do nothing`` get-or-create means a pre-existing
    live node with this slug is left untouched and simply gains the resolution.
    """
    slug = slugify(normalized_name)
    if not slug or not is_valid_slug(slug):
        return None

    row = conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status, node_kind, is_cluster_node) "
        "values (%s, %s, 'provisional', null, false) "
        "on conflict (slug) do nothing returning id",
        (slug, normalized_name),
    ).fetchone()
    if row is None:
        node_id = conn.execute(
            "select id from taxonomy_nodes where slug = %s", (slug,)
        ).fetchone()[0]
    else:
        node_id = row[0]

    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, model_id)
        values (%s, 'map-mint', %s, %s, %s)
        on conflict (node_id) do nothing
        """,
        (node_id, version, normalized_name, model_id),
    )
    write_resolution(
        conn,
        normalized_name=normalized_name,
        taxonomy_slug=slug,
        method="provisional",
        version=version,
        model_id=model_id,
    )
    return slug
