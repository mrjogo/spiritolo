"""Antichain rollup: walk the taxonomy DAG from a node up to its nearest
ancestor with is_cluster_node = true, OR return the node itself if it is
one OR if no antichain ancestor exists (the node is "above the cut").

Uses a recursive CTE. Defensive depth cap of 10 (taxonomy is shallow;
real depth is 3-5).
"""

from __future__ import annotations

import psycopg

_SQL = """
    with recursive ancestors(id, depth) as (
        select n.id, 0
        from taxonomy_nodes n
        where n.id = %s

        union all

        select e.parent_id, a.depth + 1
        from ancestors a
        join taxonomy_edges e on e.child_id = a.id
        where a.depth < 10
    ),
    matches as (
        select a.id, a.depth
        from ancestors a
        join taxonomy_nodes n on n.id = a.id
        where n.is_cluster_node = true
        order by a.depth
        limit 1
    )
    select coalesce((select id from matches), %s)
"""


def roll_up_to_antichain(conn: psycopg.Connection, node_id: int) -> int:
    """Return the antichain ancestor of node_id (or node_id itself).

    Behaviour:
      - node_id is_cluster_node=true                     → returns node_id
      - node_id has an is_cluster_node=true ancestor     → returns nearest
      - node_id has no is_cluster_node anywhere upward   → returns node_id

    The third case is the "above the cut" path — recipes referencing a
    node above the antichain (e.g., generic 'amaro') flow through with
    that node verbatim and are flagged underspecified by the audit pass.
    """
    if node_id is None:
        return node_id
    row = conn.execute(_SQL, (node_id, node_id)).fetchone()
    return row[0]
