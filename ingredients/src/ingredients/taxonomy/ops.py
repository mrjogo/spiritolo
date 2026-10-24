"""The two structural taxonomy writes, ported from the ``combine_merge`` /
``connect_place`` SQL functions.

Both run inside the caller's transaction (they open a savepoint of their own so
a failure leaves no partial edge behind) and raise :class:`TaxonomyError` for
every case the SQL version RAISEd: missing nodes, a self-merge, an unknown
parent slug, and an antichain violation.
"""

from __future__ import annotations

from collections.abc import Iterable

from common.db import SQL_NOW, Connection


class TaxonomyError(ValueError):
    """A structural taxonomy write was rejected (nothing was changed)."""


def combine_merge(conn: Connection, survivor_id: int | None, absorbed_id: int | None) -> None:
    """Merge ``absorbed_id`` into ``survivor_id``: aliases, resolutions and edges
    are repointed at the survivor, the absorbed slug + display name become
    survivor aliases, then the absorbed node (and its provenance) is deleted."""
    if survivor_id is None or absorbed_id is None:
        raise TaxonomyError("combine_merge: survivor and absorbed ids are both required")
    if survivor_id == absorbed_id:
        raise TaxonomyError(f"combine_merge: cannot merge a node into itself (id {survivor_id})")
    with conn.transaction():
        row = conn.execute("select slug from taxonomy_nodes where id = ?", (survivor_id,)).fetchone()
        if row is None:
            raise TaxonomyError(f"combine_merge: survivor node {survivor_id} not found")
        survivor_slug = row[0]
        row = conn.execute(
            "select slug, display_name from taxonomy_nodes where id = ?", (absorbed_id,)
        ).fetchone()
        if row is None:
            raise TaxonomyError(f"combine_merge: absorbed node {absorbed_id} not found")
        absorbed_slug, absorbed_name = row[0], row[1]

        # Move the absorbed node's own aliases to the survivor (keeping curated
        # spellings), then alias the absorbed slug + display name to the survivor
        # so any name that mapped to the absorbed re-lands on it.
        conn.execute(
            "update taxonomy_aliases set node_id = ? where node_id = ? and alias not in "
            "(select alias from taxonomy_aliases where node_id = ?)",
            (survivor_id, absorbed_id, survivor_id),
        )
        conn.execute("delete from taxonomy_aliases where node_id = ?", (absorbed_id,))
        conn.execute(
            "insert or ignore into taxonomy_aliases (alias, node_id) values (?, ?)",
            (absorbed_slug, survivor_id),
        )
        conn.execute(
            "insert or ignore into taxonomy_aliases (alias, node_id) values (?, ?)",
            (absorbed_name, survivor_id),
        )
        # Repoint the shared, name-keyed resolutions.
        conn.execute(
            f"update ingredient_resolutions set taxonomy_slug = ?, updated_at = {SQL_NOW} "
            "where taxonomy_slug = ?",
            (survivor_slug, absorbed_slug),
        )
        # Edges: absorbed-as-child, then absorbed-as-parent, skipping self-loops.
        conn.execute(
            "insert or ignore into taxonomy_edges (parent_id, child_id) "
            "select e.parent_id, ? from taxonomy_edges e "
            "where e.child_id = ? and e.parent_id <> ?",
            (survivor_id, absorbed_id, survivor_id),
        )
        conn.execute("delete from taxonomy_edges where child_id = ?", (absorbed_id,))
        conn.execute(
            "insert or ignore into taxonomy_edges (parent_id, child_id) "
            "select ?, e.child_id from taxonomy_edges e "
            "where e.parent_id = ? and e.child_id <> ?",
            (survivor_id, absorbed_id, survivor_id),
        )
        conn.execute("delete from taxonomy_edges where parent_id = ?", (absorbed_id,))
        conn.execute("delete from taxonomy_provenance where node_id = ?", (absorbed_id,))
        conn.execute("delete from taxonomy_nodes where id = ?", (absorbed_id,))


def antichain_conflict(conn: Connection, node_id: int) -> int | None:
    """The id of an ``is_cluster_node`` ancestor or descendant of ``node_id``,
    or ``None`` when making ``node_id`` a cluster node would keep the antichain
    invariant (no cluster node has a cluster-node relative)."""
    row = conn.execute(
        """
        with recursive ancestors(id) as (
            select e.parent_id from taxonomy_edges e where e.child_id = ?
            union
            select e.parent_id from taxonomy_edges e join ancestors a on e.child_id = a.id
        )
        select an.id from ancestors an join taxonomy_nodes n on n.id = an.id
        where n.is_cluster_node limit 1
        """,
        (node_id,),
    ).fetchone()
    if row is not None:
        return row[0]
    row = conn.execute(
        """
        with recursive descendants(id) as (
            select e.child_id from taxonomy_edges e where e.parent_id = ?
            union
            select e.child_id from taxonomy_edges e join descendants d on e.parent_id = d.id
        )
        select de.id from descendants de join taxonomy_nodes n on n.id = de.id
        where n.is_cluster_node limit 1
        """,
        (node_id,),
    ).fetchone()
    return row[0] if row is not None else None


def connect_place(
    conn: Connection,
    node_id: int | None,
    node_kind: str | None,
    parent_slugs: Iterable[str] | None,
    is_cluster_node: bool,
) -> None:
    """Attach ``node_id`` under ``parent_slugs``, set its kind + cluster flag,
    enforce the antichain invariant, and promote it to ``live``."""
    if node_id is None:
        raise TaxonomyError("connect_place: node id is required")
    if node_kind not in (None, "brand", "expression"):
        raise TaxonomyError(f"connect_place: node_kind {node_kind!r} must be brand, expression or null")
    with conn.transaction():
        if conn.execute("select 1 from taxonomy_nodes where id = ?", (node_id,)).fetchone() is None:
            raise TaxonomyError(f"connect_place: node {node_id} not found")
        for slug in parent_slugs or ():
            row = conn.execute("select id from taxonomy_nodes where slug = ?", (slug,)).fetchone()
            if row is None:
                raise TaxonomyError(f"connect_place: parent slug {slug} does not exist")
            if row[0] != node_id:
                conn.execute(
                    "insert or ignore into taxonomy_edges (parent_id, child_id) values (?, ?)",
                    (row[0], node_id),
                )
        if is_cluster_node:
            conflict = antichain_conflict(conn, node_id)
            if conflict is not None:
                raise TaxonomyError(
                    f"connect_place: antichain violation — node {node_id} would be a "
                    f"cluster node with cluster relative {conflict}"
                )
        conn.execute(
            f"update taxonomy_nodes set node_kind = ?, is_cluster_node = ?, status = 'live', "
            f"updated_at = {SQL_NOW} where id = ?",
            (node_kind, 1 if is_cluster_node else 0, node_id),
        )
