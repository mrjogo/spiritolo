"""Taxonomy curation operations behind the /ops taxonomy editor (port of the
``create_taxonomy_node`` / ``update_taxonomy_node`` / ``set_node_parents`` /
``delete_taxonomy_node`` / ``get_taxonomy_node_blockers`` SQL functions)."""

from __future__ import annotations

from typing import Any, Iterable

from common.db import SQL_NOW, Connection, jlist

from .ops import TaxonomyError


def _exists(conn: Connection, node_id: int) -> None:
    if conn.execute("select 1 from taxonomy_nodes where id = ?", (node_id,)).fetchone() is None:
        raise TaxonomyError(f"taxonomy_node {node_id} not found")


def create_node(conn: Connection, *, slug: str, display_name: str, parent_id: int | None = None,
                node_kind: str | None = None, default_role: str | None = None,
                is_cluster_node: bool = False, is_defining_garnish: bool = False,
                aliases: Iterable[str] = (), status: str = "live") -> int:
    with conn.transaction():
        if parent_id is not None:
            if conn.execute("select 1 from taxonomy_nodes where id = ?", (parent_id,)).fetchone() is None:
                raise TaxonomyError(f"parent_id {parent_id} not found")
        new_id = conn.execute(
            "insert into taxonomy_nodes (slug, display_name, node_kind, default_role, "
            "is_cluster_node, is_defining_garnish, status) values (?, ?, ?, ?, ?, ?, ?) returning id",
            (slug, display_name, node_kind or None, default_role or None,
             1 if is_cluster_node else 0, 1 if is_defining_garnish else 0, status),
        ).fetchone()[0]
        if parent_id is not None:
            conn.execute("insert into taxonomy_edges (parent_id, child_id) values (?, ?)", (parent_id, new_id))
        for a in aliases:
            if a and a.strip():
                conn.execute("insert or ignore into taxonomy_aliases (alias, node_id) values (?, ?)", (a, new_id))
    return new_id


def update_node(conn: Connection, node_id: int, patch: dict[str, Any]) -> None:
    """Apply a partial update; ``aliases`` (if present) replaces the alias set."""
    with conn.transaction():
        _exists(conn, node_id)
        sets: list[str] = []
        params: list[Any] = []
        for col in ("slug", "display_name", "status"):
            if col in patch:
                sets.append(f"{col} = ?"); params.append(patch[col])
        for col in ("node_kind", "default_role"):
            if col in patch:
                sets.append(f"{col} = ?"); params.append(patch[col] or None)
        for col in ("is_cluster_node", "is_defining_garnish"):
            if col in patch:
                sets.append(f"{col} = ?"); params.append(1 if patch[col] else 0)
        if sets:
            sets.append(f"updated_at = {SQL_NOW}")
            conn.execute(f"update taxonomy_nodes set {', '.join(sets)} where id = ?", (*params, node_id))
        if "aliases" in patch:
            conn.execute("delete from taxonomy_aliases where node_id = ?", (node_id,))
            for a in patch["aliases"] or []:
                if a and str(a).strip():
                    conn.execute("insert or ignore into taxonomy_aliases (alias, node_id) values (?, ?)", (a, node_id))


def set_parents(conn: Connection, node_id: int, parent_ids: Iterable[int] | None) -> None:
    parents = [int(p) for p in (parent_ids or []) if p is not None]
    with conn.transaction():
        _exists(conn, node_id)
        if node_id in parents:
            raise TaxonomyError("cycle: a node cannot be its own parent")
        if parents:
            row = conn.execute(
                """
                with recursive descendants(id) as (
                    select child_id from taxonomy_edges where parent_id = ?
                    union
                    select e.child_id from taxonomy_edges e join descendants d on e.parent_id = d.id
                )
                select 1 from descendants where id in (select value from json_each(?)) limit 1
                """,
                (node_id, jlist(parents)),
            ).fetchone()
            if row is not None:
                raise TaxonomyError(f"cycle: at least one proposed parent is a descendant of node {node_id}")
        conn.execute("delete from taxonomy_edges where child_id = ?", (node_id,))
        for p in parents:
            conn.execute("insert or ignore into taxonomy_edges (parent_id, child_id) values (?, ?)", (p, node_id))


def blockers(conn: Connection, node_id: int) -> dict[str, Any]:
    """What stands in the way of deleting a node (children, references...)."""
    def count(sql: str) -> int:
        return conn.execute(sql, (node_id,)).fetchone()[0]

    children = conn.execute(
        "select n.id, n.display_name from taxonomy_edges e join taxonomy_nodes n on n.id = e.child_id "
        "where e.parent_id = ? order by n.display_name",
        (node_id,),
    ).fetchall()
    return {
        "children": len(children),
        "child_names": [{"id": r[0], "display_name": r[1]} for r in children],
        "parents": count("select count(*) from taxonomy_edges where child_id = ?"),
        "aliases": count("select count(*) from taxonomy_aliases where node_id = ?"),
        "provenance": count("select count(*) from taxonomy_provenance where node_id = ?"),
        "recipe_ingredients": count(
            "select count(*) from recipe_ingredients ri "
            "join ingredient_resolutions ir on lower(trim(ri.name)) = ir.normalized_name "
            "join taxonomy_nodes n on n.slug = ir.taxonomy_slug where n.id = ?"
        ),
        "form_proposals": count(
            "select count(*) from human_reviews where stage = 'map-ingredient' "
            "and origin = 'machine_proposal' and state = 'open' "
            "and payload ->> '$.proposed_parent_id' = cast(? as text)"
        ),
    }


def delete_node(conn: Connection, node_id: int) -> None:
    with conn.transaction():
        _exists(conn, node_id)
        b = blockers(conn, node_id)
        if b["children"] or b["recipe_ingredients"] or b["form_proposals"]:
            raise TaxonomyError(
                f"blocked: {b['children']} children, {b['recipe_ingredients']} recipe references, "
                f"{b['form_proposals']} form proposal references"
            )
        conn.execute("delete from taxonomy_nodes where id = ?", (node_id,))
