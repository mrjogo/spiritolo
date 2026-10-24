"""The generic paged read endpoint behind the ``/ops`` browsers.

The React ops console was written against PostgREST's ``select / eq / in /
order / range`` chain. This reproduces exactly that surface over an explicit
allowlist of tables and views: column names are validated against the live
schema (``pragma table_info``), operators are a fixed set, values are always
bound parameters. Nothing here can touch a table that is not listed.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from common.db import Connection, jlist

# Tables/views the ops console may read. Everything else is a 404.
READABLE = frozenset({
    "recipes", "recipes_public", "recipe_ingredients", "recipe_steps", "recipe_exports",
    "recipe_clusters", "ingredient_resolutions", "taxonomy_nodes", "taxonomy_edges",
    "taxonomy_aliases", "taxonomy_public", "cocktail_aliases", "pages",
    "jobs", "job_items", "runs", "human_reviews", "needs_review", "audit_log_public",
    "operators",
})
# Columns never returned (none of the listed tables carry secrets today, but
# ``operators``/``passkeys`` are kept out of reach by construction).
OPS = {"eq", "neq", "in", "lt", "lte", "gt", "gte", "ilike", "like", "is"}
MAX_LIMIT = 1000

_columns_cache: dict[str, dict[str, str]] = {}


def columns(conn: Connection, table: str) -> dict[str, str]:
    """``{name: declared_type}`` for a table or view (cached per process)."""
    cols = _columns_cache.get(table)
    if cols is None:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        cols = {r["name"]: (r["type"] or "").upper() for r in rows}
        _columns_cache[table] = cols
    return cols


def _ident(name: str, cols: dict[str, str]) -> str:
    if name not in cols:
        raise HTTPException(400, f"unknown column {name!r}")
    return f'"{name}"'


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalise_pattern(value: Any) -> str:
    # PostgREST accepted `*` as a wildcard alias; LIKE wants `%`.
    return str(value).replace("*", "%")


def build_query(conn: Connection, spec: dict[str, Any]) -> tuple[str, str, list[Any], dict[str, str], list[str]]:
    """``(select_sql, from_sql, params, columns, selected)`` for a spec."""
    table = spec.get("table")
    if not isinstance(table, str) or table not in READABLE:
        raise HTTPException(404, f"unknown table {table!r}")
    cols = columns(conn, table)
    if not cols:
        raise HTTPException(404, f"unknown table {table!r}")

    select = spec.get("select") or "*"
    if select == "*":
        selected = list(cols)
    else:
        selected = [c.strip() for c in str(select).split(",") if c.strip()]
        for c in selected:
            _ident(c, cols)
    select_sql = ", ".join(f'"{c}"' for c in selected)

    where: list[str] = []
    params: list[Any] = []
    for f in spec.get("filters") or []:
        col, op, value = f.get("col"), f.get("op"), f.get("value")
        ident = _ident(str(col), cols)
        if op not in OPS:
            raise HTTPException(400, f"unknown operator {op!r}")
        if op == "in":
            values = value if isinstance(value, list) else [value]
            where.append(f"{ident} in (select value from json_each(?))")
            params.append(jlist(values))
        elif op == "is":
            if value is None or value == "null":
                where.append(f"{ident} is null")
            elif value in (True, "true"):
                where.append(f"{ident} = 1")
            elif value in (False, "false"):
                where.append(f"{ident} = 0")
            else:
                raise HTTPException(400, "is expects null/true/false")
        elif op in ("ilike", "like"):
            where.append(f"{ident} like ? escape '\\'")
            params.append(_normalise_pattern(value))
        else:
            sym = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
            if value is None and op == "eq":
                where.append(f"{ident} is null")
            elif value is None and op == "neq":
                where.append(f"{ident} is not null")
            else:
                where.append(f"{ident} {sym} ?")
                params.append(_bind(value))
    # Free-text search: every term must match one of the given columns.
    search = spec.get("search")
    if isinstance(search, dict) and search.get("terms"):
        scols = [_ident(str(c), cols) for c in search.get("cols") or []]
        if not scols:
            raise HTTPException(400, "search needs cols")
        for term in search["terms"]:
            where.append("(" + " or ".join(f"{c} like ? escape '\\'" for c in scols) + ")")
            params.extend(["%" + _like_escape(str(term)) + "%"] * len(scols))

    where_sql = (" where " + " and ".join(where)) if where else ""
    return select_sql, f"from {table}{where_sql}", params, cols, selected


def _bind(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def run_query(conn: Connection, spec: dict[str, Any]) -> dict[str, Any]:
    """``{rows, total}`` for a query spec ``{table, select, filters, search,
    order, offset, limit}``."""
    select_sql, from_sql, params, cols, selected = build_query(conn, spec)
    order_sql = ""
    order = spec.get("order")
    if order:
        orders = order if isinstance(order, list) else [order]
        parts = []
        for o in orders:
            ident = _ident(str(o.get("col")), cols)
            direction = "asc" if o.get("asc", True) else "desc"
            parts.append(f"{ident} {direction}" + (" nulls last" if direction == "asc" else ""))
        order_sql = " order by " + ", ".join(parts)
    limit = min(int(spec.get("limit") or 50), MAX_LIMIT)
    offset = max(int(spec.get("offset") or 0), 0)
    total = conn.execute(f"select count(*) {from_sql}", params).fetchone()[0]
    rows = conn.execute(
        f"select {select_sql} {from_sql}{order_sql} limit ? offset ?", (*params, limit, offset)
    ).fetchall()
    return {"rows": [decode_row(r, cols) for r in rows], "total": total}


def decode_row(row: Any, cols: dict[str, str]) -> dict[str, Any]:
    """A row as JSON-ready dict: declared JSON/boolean columns are already
    converted by the connection; view columns (no declared type) holding JSON
    arrays/objects are parsed here so the client sees structure, not text."""
    out = row.asdict()
    for k, v in out.items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = v.hex()
        elif isinstance(v, str) and not cols.get(k) and v[:1] in "[{":
            try:
                out[k] = json.loads(v)
            except ValueError:
                pass
    return out
