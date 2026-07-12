"""Schema + behavior + boundary tests for the recipe_docs content table
and the recipes_public read surface (B2).

Runs against TEST_DB_URL with all migrations applied (the ingredients conftest
auto-applies the new 20260712_010000_recipe_docs.sql). recipe_docs is the
source-of-truth content table: one RecipeGF-shaped JSONB doc per recipe, with
generated projection columns, a jsonb_path_ops GIN + trgm indexes, deny-write
RLS, and the security_invoker recipes_public view that preserves the current
public column contract (id, source_url, site, name, author, image_url, jsonld).
"""

from __future__ import annotations

import json

import psycopg
import pytest
from psycopg.types.json import Json


def _doc(**over) -> dict:
    """A minimal spiritolo/recipe-doc/v1 doc with an _x sidecar."""
    d = {
        "schema": "recipegf/cocktail/v1",
        "id": "com.spiritolo/negroni:v1",
        "title": "Negroni",
        "ingredients": [{"name": "Campari", "ref": "spiritolo/campari"}],
        "steps": [],
        "_x": {
            "site": "punch",
            "canonical_name": "Negroni",
            "cluster_key": "sha256:abc",
            "variant_key": "sha256:def",
            "source": {
                "jsonld": {
                    "name": "Negroni",
                    "author": "Punch Editorial",
                    "image": "https://ex/negroni.jpg",
                },
                "jsonld_origin": "verbatim",
            },
        },
    }
    d.update(over)
    return d


def _reset_table(conn) -> None:
    conn.execute("truncate table recipe_docs restart identity cascade")


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_columns_and_types(db_conn):
    cols = {
        r[0]: (r[1], r[2], r[3], r[4])
        for r in db_conn.execute(
            """
            select column_name, data_type, is_nullable, column_default, is_generated
            from information_schema.columns
            where table_name = 'recipe_docs'
            """
        ).fetchall()
    }
    # base columns
    assert cols["id"][0] == "bigint"
    assert cols["id"][1] == "NO"
    assert cols["source_url"][0] == "text"
    assert cols["source_url"][1] == "NO"
    assert cols["doc"][0] == "jsonb"
    assert cols["doc"][1] == "NO"
    assert cols["doc_schema"][0] == "text"
    assert cols["doc_schema"][1] == "NO"
    assert "spiritolo/recipe-doc/v1" in (cols["doc_schema"][2] or "")
    assert cols["state"][0] == "text"
    assert cols["state"][1] == "NO"
    assert "extracted" in (cols["state"][2] or "")
    assert cols["updated_at"][0] == "timestamp with time zone"
    assert cols["updated_at"][1] == "NO"

    # id is the primary key
    pk = db_conn.execute(
        """
        select kcu.column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
        where tc.table_name = 'recipe_docs'
          and tc.constraint_type = 'PRIMARY KEY'
        """
    ).fetchall()
    assert [r[0] for r in pk] == ["id"]

    # generated projection columns
    for gcol in ("site", "canonical_name", "cluster_key", "variant_key", "title"):
        assert cols[gcol][0] == "text", gcol
        assert cols[gcol][3] == "ALWAYS", f"{gcol} should be a generated column"


def test_state_check_constraint(db_conn):
    clauses = [
        r[0]
        for r in db_conn.execute(
            """
            select cc.check_clause
            from information_schema.check_constraints cc
            join information_schema.constraint_column_usage ccu
              on cc.constraint_name = ccu.constraint_name
            where ccu.table_name = 'recipe_docs' and ccu.column_name = 'state'
            """
        ).fetchall()
    ]
    joined = " ".join(clauses)
    for s in ("extracted", "parsed", "mapped", "clustered", "exported"):
        assert s in joined, f"state CHECK missing {s}: {joined!r}"

    _reset_table(db_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "insert into recipe_docs (source_url, doc, state) values (%s, %s, %s)",
            ("https://ex/badstate", Json(_doc()), "bogus"),
        )


def test_source_url_unique(db_conn):
    _reset_table(db_conn)
    db_conn.execute(
        "insert into recipe_docs (source_url, doc) values (%s, %s)",
        ("https://ex/dup", Json(_doc())),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            "insert into recipe_docs (source_url, doc) values (%s, %s)",
            ("https://ex/dup", Json(_doc(title="Other"))),
        )


# --------------------------------------------------------------------------
# Behavior — generated columns track the doc
# --------------------------------------------------------------------------

def test_generated_columns_track_doc(db_conn):
    _reset_table(db_conn)
    doc_id = db_conn.execute(
        "insert into recipe_docs (source_url, doc) values (%s, %s) returning id",
        ("https://ex/gen", Json(_doc())),
    ).fetchone()[0]

    row = db_conn.execute(
        "select site, canonical_name, cluster_key, variant_key, title "
        "from recipe_docs where id = %s",
        (doc_id,),
    ).fetchone()
    assert row == ("punch", "Negroni", "sha256:abc", "sha256:def", "Negroni")

    # Mutate the doc; generated columns must follow.
    new_doc = _doc(title="Boulevardier")
    new_doc["_x"]["site"] = "seriouseats"
    new_doc["_x"]["canonical_name"] = "Boulevardier"
    new_doc["_x"]["cluster_key"] = "sha256:zzz"
    new_doc["_x"]["variant_key"] = "sha256:yyy"
    db_conn.execute(
        "update recipe_docs set doc = %s where id = %s", (Json(new_doc), doc_id)
    )
    row = db_conn.execute(
        "select site, canonical_name, cluster_key, variant_key, title "
        "from recipe_docs where id = %s",
        (doc_id,),
    ).fetchone()
    assert row == (
        "seriouseats", "Boulevardier", "sha256:zzz", "sha256:yyy", "Boulevardier",
    )


# --------------------------------------------------------------------------
# Indexes — jsonb_path_ops GIN + trgm, and the GIN is planner-usable
# --------------------------------------------------------------------------

def test_gin_and_trgm_indexes_exist(db_conn):
    defs = {
        r[0]: r[1]
        for r in db_conn.execute(
            "select indexname, indexdef from pg_indexes where tablename = 'recipe_docs'"
        ).fetchall()
    }
    gin_defs = [d for d in defs.values() if "jsonb_path_ops" in d and "gin" in d.lower()]
    assert gin_defs, f"missing gin(doc jsonb_path_ops) index; have {defs}"
    assert any("(doc " in d or "(doc)" in d for d in gin_defs)

    trgm_cols = {
        col
        for d in defs.values()
        if "gin_trgm_ops" in d
        for col in ("title", "canonical_name")
        if col in d
    }
    assert "title" in trgm_cols, f"missing trgm index on title; have {defs}"
    assert "canonical_name" in trgm_cols, f"missing trgm index on canonical_name; have {defs}"

    # The @> containment query planner-uses the jsonb_path_ops GIN.
    _reset_table(db_conn)
    db_conn.execute(
        "insert into recipe_docs (source_url, doc) values (%s, %s)",
        ("https://ex/gin1", Json(_doc(ingredients=[{"ref": "spiritolo/gin"}]))),
    )
    db_conn.execute("set enable_seqscan = off")
    try:
        plan = "\n".join(
            r[0]
            for r in db_conn.execute(
                "explain select 1 from recipe_docs "
                "where doc @> '{\"ingredients\":[{\"ref\":\"spiritolo/gin\"}]}'::jsonb"
            ).fetchall()
        )
    finally:
        db_conn.execute("set enable_seqscan = on")
    assert "recipe_docs_doc_gin" in plan, plan


# --------------------------------------------------------------------------
# Boundary — RLS denies anon writes; recipes_public readable as anon
# --------------------------------------------------------------------------

def test_rls_denies_anon_direct_write(db_conn):
    _reset_table(db_conn)
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute(
                "insert into recipe_docs (source_url, doc) values (%s, %s)",
                ("https://ex/anon-write", Json(_doc())),
            )
    finally:
        db_conn.execute("reset role")


def test_recipes_public_columns_selectable_as_anon(db_conn):
    # Public column contract preserved from the current recipes_public.
    view_cols = {
        r[0]
        for r in db_conn.execute(
            "select column_name from information_schema.columns "
            "where table_name = 'recipes_public'"
        ).fetchall()
    }
    assert view_cols == {
        "id", "source_url", "site", "name", "author", "image_url", "jsonld",
    }

    _reset_table(db_conn)
    db_conn.execute(
        "insert into recipe_docs (source_url, doc) values (%s, %s)",
        ("https://ex/pub", Json(_doc())),
    )

    db_conn.execute("set role anon")
    try:
        row = db_conn.execute(
            "select id, source_url, site, name, author, image_url, jsonld "
            "from recipes_public where source_url = %s",
            ("https://ex/pub",),
        ).fetchone()
    finally:
        db_conn.execute("reset role")

    assert row is not None, "anon SELECT on recipes_public returned no rows"
    _id, source_url, site, name, author, image_url, jsonld = row
    assert source_url == "https://ex/pub"
    assert site == "punch"
    assert name == "Negroni"  # doc.title
    assert author == "Punch Editorial"
    assert image_url == "https://ex/negroni.jpg"
    assert jsonld == {
        "name": "Negroni",
        "author": "Punch Editorial",
        "image": "https://ex/negroni.jpg",
    }


def test_recipes_public_name_falls_back_to_jsonld_name(db_conn):
    _reset_table(db_conn)
    d = _doc()
    del d["title"]  # no envelope title -> fall back to jsonld name
    db_conn.execute(
        "insert into recipe_docs (source_url, doc) values (%s, %s)",
        ("https://ex/noname", Json(d)),
    )
    name = db_conn.execute(
        "select name from recipes_public where source_url = %s", ("https://ex/noname",)
    ).fetchone()[0]
    assert name == "Negroni"  # from _x.source.jsonld.name
