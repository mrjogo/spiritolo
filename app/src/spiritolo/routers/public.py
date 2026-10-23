"""The public read API the recipe pages use (no login)."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from common.db import Connection

from ..deps import conn, current_operator
from ..query import columns, decode_row

router = APIRouter(prefix="/api", tags=["public"])

MIN_TERM_LENGTH = 3
MAX_INPUT_LENGTH = 200
_EDGE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")


def search_terms(q: str) -> list[str]:
    """Mirror of the web app's ``buildSearchFilters``: whitespace-split,
    strip punctuation at the edges, drop terms under three characters."""
    out = []
    for raw in q[:MAX_INPUT_LENGTH].split():
        t = _EDGE.sub("", raw)
        if len(t) >= MIN_TERM_LENGTH:
            out.append(t)
    return out


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/recipes")
def list_recipes(c: Connection = Depends(conn), q: str = "", page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    for term in search_terms(q):
        where.append("(title like ? escape '\\' or json_extract(source, '$.recipeIngredient') like ? escape '\\')")
        params.extend([_like(term), _like(term)])
    where_sql = (" where " + " and ".join(where)) if where else ""
    total = c.execute(f"select count(*) from recipes{where_sql}", params).fetchone()[0]
    rows = c.execute(
        f"select id, site, title as name, image_url from recipes{where_sql} "
        "order by title is null, title collate nocase, id limit ? offset ?",
        (*params, page_size, (page - 1) * page_size),
    ).fetchall()
    return {"rows": [r.asdict() for r in rows], "total": total}


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, c: Connection = Depends(conn)) -> dict[str, Any]:
    row = c.execute("select * from recipes_public where id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "recipe not found")
    out = decode_row(row, columns(c, "recipes_public"))
    if isinstance(out.get("jsonld"), str):
        out["jsonld"] = json.loads(out["jsonld"])
    return out


@router.get("/recipes/{recipe_id}/ingredients")
def recipe_ingredients(recipe_id: int, c: Connection = Depends(conn), op=Depends(current_operator)) -> list[dict[str, Any]]:
    """Parsed ingredient rows joined to their resolved taxonomy node. Operator
    only: the public page shows the Schema.org text, the parsed panel is a
    curation surface."""
    if op is None:
        raise HTTPException(401, "sign in required")
    rows = c.execute(
        """
        select ri.id, ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit, ri.name,
               ri.modifiers, ir.taxonomy_slug, ir.method as resolution_method,
               n.id as taxonomy_node_id, n.display_name as taxonomy_display_name, n.status as taxonomy_status
        from recipe_ingredients ri
        left join ingredient_resolutions ir on ir.normalized_name = lower(trim(ri.name))
        left join taxonomy_nodes n on n.slug = ir.taxonomy_slug
        where ri.recipe_id = ? order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = r.asdict()
        node = None
        if d.pop("taxonomy_slug", None) and d.get("taxonomy_node_id") is not None:
            node = {"id": d["taxonomy_node_id"], "slug": r["taxonomy_slug"],
                    "display_name": d.pop("taxonomy_display_name"), "status": d.pop("taxonomy_status")}
        else:
            d.pop("taxonomy_display_name", None); d.pop("taxonomy_status", None)
        d["taxonomy_node"] = node
        d["modifiers"] = d.get("modifiers") or []
        out.append(d)
    return out


@router.get("/taxonomy")
def taxonomy(c: Connection = Depends(conn)) -> list[dict[str, Any]]:
    cols = columns(c, "taxonomy_public")
    rows = c.execute("select * from taxonomy_public order by id").fetchall()
    out = []
    for r in rows:
        d = decode_row(r, cols)
        for k in ("parent_ids", "child_ids", "aliases"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        d["is_cluster_node"] = bool(d["is_cluster_node"])
        d["is_defining_garnish"] = bool(d["is_defining_garnish"])
        out.append(d)
    return out


@router.get("/taxonomy/{node_id}/recipes")
def taxonomy_recipes(node_id: int, c: Connection = Depends(conn)) -> list[dict[str, Any]]:
    """Recipes using a taxonomy node (through the shared name-keyed resolutions)."""
    rows = c.execute(
        """
        select distinct r.id, r.title as name, r.site
        from taxonomy_nodes n
        join ingredient_resolutions ir on ir.taxonomy_slug = n.slug
        join recipe_ingredients ri on lower(trim(ri.name)) = ir.normalized_name
        join recipes r on r.id = ri.recipe_id
        where n.id = ? order by r.site, r.title collate nocase
        """,
        (node_id,),
    ).fetchall()
    return [r.asdict() for r in rows]
