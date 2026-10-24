"""Apply a resolved human review to the live content rows.

Port of the ``apply_review`` SQL function. The review row is the durable truth;
this stamps its payload onto the stage's output table so the human value wins
the live row. Idempotent: re-applying the same payload is a no-op. Used by the
ops API when a curator resolves a review and by the pipeline's post-run
re-apply (``reviews.reapply``).
"""

from __future__ import annotations

from typing import Any

from common.db import SQL_NOW, Connection, jdump, jload

from ingredients.taxonomy import combine_merge, connect_place


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def apply_review(conn: Connection, review_id: int) -> bool:
    """Apply review ``review_id`` if it is ``resolved``; return whether it was."""
    row = conn.execute(
        "select stage, entity_id, payload from human_reviews where id = ? and state = 'resolved'",
        (review_id,),
    ).fetchone()
    if row is None:
        return False
    stage, entity_id, payload = row[0], row[1], jload(row[2], {}) or {}

    if stage == "map-ingredient":
        cur = conn.execute(
            f"update ingredient_resolutions set taxonomy_slug = ?, method = 'manual', "
            f"updated_at = {SQL_NOW} where normalized_name = ?",
            (payload.get("slug"), entity_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
                "values (?, ?, 'manual', 'override')",
                (entity_id, payload.get("slug")),
            )
    elif stage == "parse-ingredients":
        recipe_id, _, position = entity_id.partition(":")
        conn.execute(
            "update recipe_ingredients set "
            "name = coalesce(?, name), amount = coalesce(?, amount), "
            "amount_max = coalesce(?, amount_max), unit = coalesce(?, unit) "
            "where recipe_id = ? and position = ?",
            (
                payload.get("name"), _num(payload.get("amount")),
                _num(payload.get("amount_max")), payload.get("unit"),
                int(recipe_id), int(position),
            ),
        )
    elif stage == "cluster-recipes":
        conn.execute(
            f"update recipes set cluster_id = coalesce(?, cluster_id), "
            f"variant_key = coalesce(?, variant_key), "
            f"canonical_name = coalesce(?, canonical_name), updated_at = {SQL_NOW} where id = ?",
            (payload.get("cluster_id"), payload.get("variant_key"),
             payload.get("canonical_name"), int(entity_id)),
        )
    elif stage == "extract-recipe":
        conn.execute(
            f"update recipes set title = coalesce(?, title), author = coalesce(?, author), "
            f"image_url = coalesce(?, image_url), updated_at = {SQL_NOW} where id = ?",
            (payload.get("title"), payload.get("author"), payload.get("image_url"), int(entity_id)),
        )
    elif stage == "convert-steps":
        rid = int(entity_id)
        with conn.transaction():
            conn.execute("delete from recipe_steps where recipe_id = ?", (rid,))
            for idx, step in enumerate(payload.get("steps") or []):
                conn.execute(
                    "insert into recipe_steps (recipe_id, step_index, verb, roles, result, modifiers) "
                    "values (?, ?, ?, ?, ?, ?)",
                    (
                        rid, idx, step.get("verb"), jdump(step.get("roles") or {}),
                        step.get("result"), jdump(list(step.get("modifiers") or [])),
                    ),
                )
    elif stage == "combine-nodes":
        # absorbed = the node under review (entity_id); only survivor_id comes from
        # the curator's payload, so a mistyped/omitted id can't merge the wrong node.
        survivor = payload.get("survivor_id")
        combine_merge(conn, int(survivor) if survivor is not None else None, int(entity_id))
    elif stage == "connect-nodes":
        connect_place(
            conn,
            int(entity_id),
            payload.get("node_kind"),
            list(payload.get("parent_slugs") or []),
            bool(payload.get("is_cluster_node", False)),
        )
    return True
