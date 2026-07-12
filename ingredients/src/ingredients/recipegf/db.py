"""DB access for the RecipeGF export stage. Pure-SQL helpers; the caller
passes the psycopg connection (matches dedup/mapping ``db.py`` convention).

The verb-frame recipe is stored **relationally** — ``recipegf_recipes`` (header)
+ ``recipegf_ingredients`` + ``recipegf_steps`` rows — the way the parser stores
``recipe_ingredients``, not as an opaque JSON blob. :func:`generate_bundle`
reconstructs the pin-2 bundle deterministically from those rows on demand.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from .converter import Ok, SourceIngredient, SourceRecipe
from .verbs import is_spiritolo_verb, spiritolo_verb_defs, verb_defs_for
from .version import RECIPE_SCHEMA

_RESERVED_STEP_KEYS = {"verb", "result", "modifiers"}


# --------------------------------------------------------------------------
# Read side: source recipes + the export work queue
# --------------------------------------------------------------------------


def fetch_export_queue(
    conn: psycopg.Connection,
    *,
    converter_version: str,
    site: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Clusters with no ``recipegf_recipes`` row at the current
    CONVERTER_VERSION (a NOT EXISTS, exactly like the parser's queue) and a
    resolvable representative recipe. ``site`` scopes on the representative
    recipe's site."""
    params: list[Any] = [converter_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)
    sql = f"""
        select c.id, c.canonical_name, c.representative_recipe_id,
               r.source_url, r.jsonld
        from recipe_clusters c
        join recipes r on r.id = c.representative_recipe_id
        where not exists (
            select 1 from recipegf_recipes rr
            where rr.cluster_id = c.id and rr.converter_version = %s
        )
          {site_clause}
        order by c.id
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "cluster_id": r[0], "canonical_name": r[1],
            "representative_recipe_id": r[2], "source_url": r[3], "jsonld": r[4],
        }
        for r in rows
    ]


def fetch_source_ingredients(
    conn: psycopg.Connection, recipe_id: int
) -> list[SourceIngredient]:
    """The parsed+roled ingredients of one recipe, joined to their taxonomy
    slug, as :class:`SourceIngredient` rows ordered by position."""
    rows = conn.execute(
        """
        select ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit,
               ri.name, ri.role, tn.slug
        from recipe_ingredients ri
        left join taxonomy_nodes tn on tn.id = ri.taxonomy_node_id
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    return [
        SourceIngredient(
            position=r[0], raw_text=r[1],
            amount=float(r[2]) if r[2] is not None else None,
            amount_max=float(r[3]) if r[3] is not None else None,
            unit=r[4], name=r[5], role=r[6], slug=r[7],
        )
        for r in rows
    ]


def build_source_recipe(
    conn: psycopg.Connection, queue_row: dict[str, Any]
) -> SourceRecipe:
    """Assemble a :class:`SourceRecipe` from a ``fetch_export_queue`` row."""
    ingredients = fetch_source_ingredients(conn, queue_row["representative_recipe_id"])
    return SourceRecipe(
        canonical_name=queue_row["canonical_name"],
        source_url=queue_row["source_url"] or "",
        jsonld=queue_row["jsonld"] or {},
        ingredients=ingredients,
    )


# --------------------------------------------------------------------------
# Write side: decompose a converted recipe into rows
# --------------------------------------------------------------------------


def write_recipe(
    conn: psycopg.Connection,
    *,
    cluster_id: int,
    result: Ok,
    source: str,
    converter_version: str,
) -> int:
    """Persist a successful conversion relationally: a ``recipegf_recipes``
    header + its ``recipegf_ingredients`` and ``recipegf_steps`` rows. Replaces
    any prior row for this (cluster, version). Returns the header id. Caller
    commits."""
    recipe = result.recipe
    conn.execute(
        "delete from recipegf_recipes where cluster_id = %s and converter_version = %s",
        (cluster_id, converter_version),
    )
    header_id = conn.execute(
        """
        insert into recipegf_recipes
            (cluster_id, status, slug, recipe_id, title, technique, equipment,
             source_url, converter_version)
        values (%s, 'exported', %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (cluster_id, result.slug, recipe["id"], recipe["title"], result.technique,
         recipe.get("equipment") or [], source, converter_version),
    ).fetchone()[0]

    for pos, ing in enumerate(recipe.get("ingredients") or []):
        q = ing["quantity"]
        conn.execute(
            "insert into recipegf_ingredients "
            "(recipegf_recipe_id, position, name, amount, unit) "
            "values (%s, %s, %s, %s, %s)",
            (header_id, pos, ing["name"], q["amount"], q["unit"]),
        )

    for idx, step in enumerate(recipe.get("steps") or []):
        roles = {k: v for k, v in step.items() if k not in _RESERVED_STEP_KEYS}
        modifiers = step.get("modifiers")
        conn.execute(
            "insert into recipegf_steps "
            "(recipegf_recipe_id, step_index, verb, result, roles, modifiers) "
            "values (%s, %s, %s, %s, %s::jsonb, %s::jsonb)",
            (header_id, idx, step["verb"], step["result"], json.dumps(roles),
             json.dumps(modifiers) if modifiers is not None else None),
        )
    return header_id


def park_uncertain(
    conn: psycopg.Connection,
    *,
    cluster_id: int,
    proposed_slug: str | None,
    source: str,
    converter_version: str,
) -> None:
    """Write an ``uncertain`` header (no children) so the cluster drops off the
    queue until a version bump or reset. Pairs with a recipegf_proposals row.
    Caller commits."""
    conn.execute(
        "delete from recipegf_recipes where cluster_id = %s and converter_version = %s",
        (cluster_id, converter_version),
    )
    conn.execute(
        """
        insert into recipegf_recipes
            (cluster_id, status, slug, source_url, converter_version)
        values (%s, 'uncertain', %s, %s, %s)
        """,
        (cluster_id, proposed_slug, source, converter_version),
    )


# --------------------------------------------------------------------------
# Verb-def cache: keep the DB copy of the in-repo spiritolo/ verb-defs fresh
# --------------------------------------------------------------------------


def sync_verb_defs(conn: psycopg.Connection) -> int:
    """Refresh ``recipegf_verb_defs`` from the in-repo YAML (the source of
    truth) so the ``recipegf_bundle`` RPC can return a self-contained bundle.

    Idempotent upsert of every ``spiritolo/`` verb-def. Called at the start of
    an export run (see ``export.run_export``), so a bundle row and the verb-defs
    its steps reference are always written together — no drift, no manual sync.
    Caller commits. Returns the number of verb-defs written."""
    defs = spiritolo_verb_defs()
    for verb, definition in defs.items():
        conn.execute(
            "insert into recipegf_verb_defs (verb, definition, updated_at) "
            "values (%s, %s::jsonb, now()) "
            "on conflict (verb) do update "
            "set definition = excluded.definition, updated_at = now()",
            (verb, json.dumps(definition)),
        )
    return len(defs)


# --------------------------------------------------------------------------
# Bundle generation: recompose the pin-2 bundle from the relational rows
# --------------------------------------------------------------------------


def generate_bundle(
    conn: psycopg.Connection, *, cluster_id: int, converter_version: str
) -> dict[str, Any] | None:
    """Reconstruct a drink's pin-2 bundle from its stored rows, deterministically.

    This is the canonical "generate a bundle" path (what a P3 pull-by-slug
    reads). Returns ``None`` if there is no ``exported`` row for this
    (cluster, version). The bundle is byte-for-byte equivalent to what the
    converter produced at export time (see the roundtrip test).
    """
    header = conn.execute(
        """
        select id, slug, recipe_id, title, equipment, source_url, exported_at
        from recipegf_recipes
        where cluster_id = %s and converter_version = %s and status = 'exported'
        """,
        (cluster_id, converter_version),
    ).fetchone()
    if header is None:
        return None
    header_id, slug, recipe_id, title, equipment, source_url, exported_at = header

    ing_rows = conn.execute(
        "select name, amount, unit from recipegf_ingredients "
        "where recipegf_recipe_id = %s order by position",
        (header_id,),
    ).fetchall()
    ingredients = [
        {"name": name, "quantity": {"amount": float(amount), "unit": unit}}
        for name, amount, unit in ing_rows
    ]

    step_rows = conn.execute(
        "select verb, result, roles, modifiers from recipegf_steps "
        "where recipegf_recipe_id = %s order by step_index",
        (header_id,),
    ).fetchall()
    steps: list[dict[str, Any]] = []
    for verb, result, roles, modifiers in step_rows:
        step: dict[str, Any] = {"verb": verb, **(roles or {}), "result": result}
        if modifiers is not None:
            step["modifiers"] = modifiers
        steps.append(step)

    recipe = {
        "schema": RECIPE_SCHEMA,
        "id": recipe_id,
        "title": title,
        "ingredients": ingredients,
        "equipment": list(equipment or []),
        "steps": steps,
    }
    used = sorted({s["verb"] for s in steps if is_spiritolo_verb(s["verb"])})
    return {
        "recipe": recipe,
        "verbs": verb_defs_for(used),
        "meta": {
            "slug": slug,
            "source": source_url or "",
            "imported_at": exported_at.isoformat(),
        },
    }


def generate_bundle_by_slug(
    conn: psycopg.Connection, *, slug: str, converter_version: str
) -> dict[str, Any] | None:
    """Slug-keyed pull: resolve ``slug`` → ``cluster_id`` (among ``exported``
    rows at ``converter_version``) then reconstruct the bundle via
    :func:`generate_bundle`. Returns ``None`` when no exported row matches.

    This is the read path Barbot's P3 import uses to fetch a drink by its
    Spiritolo slug (the sync key), rather than by cluster id. It is the Python
    twin of the ``recipegf_bundle(slug, converter_version)`` RPC — both project
    the same relational rows; a DB parity test pins them equal.
    """
    row = conn.execute(
        "select cluster_id from recipegf_recipes "
        "where slug = %s and converter_version = %s and status = 'exported' "
        "limit 1",
        (slug, converter_version),
    ).fetchone()
    if row is None:
        return None
    return generate_bundle(
        conn, cluster_id=row[0], converter_version=converter_version
    )


# --------------------------------------------------------------------------
# Reset
# --------------------------------------------------------------------------


def count_recipe_headers(
    conn: psycopg.Connection,
    *,
    except_version: str | None = None,
    older_than: str | None = None,
) -> int:
    """Count ``recipegf_recipes`` headers a ``--reset`` would clear (both
    ``exported`` and parked ``uncertain`` headers — reset re-queues either)."""
    sql = "select count(*) from recipegf_recipes where true"
    params: list[Any] = []
    if except_version is not None:
        sql += " and converter_version <> %s"
        params.append(except_version)
    if older_than is not None:
        sql += " and exported_at < %s"
        params.append(older_than)
    return conn.execute(sql, params).fetchone()[0]


def clear_recipe_headers(
    conn: psycopg.Connection,
    *,
    except_version: str | None = None,
    older_than: str | None = None,
) -> int:
    """Delete ``recipegf_recipes`` headers in scope (children cascade), so the
    clusters re-queue. Clears both exported and parked-uncertain headers.
    Caller commits. Returns rowcount."""
    sql = "delete from recipegf_recipes where true"
    params: list[Any] = []
    if except_version is not None:
        sql += " and converter_version <> %s"
        params.append(except_version)
    if older_than is not None:
        sql += " and exported_at < %s"
        params.append(older_than)
    cur = conn.execute(sql, params)
    return cur.rowcount
