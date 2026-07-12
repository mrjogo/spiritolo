"""Schema + behavior + boundary tests for the recipe_docs content table
and the recipes_public read surface (B2).

Runs against TEST_DB_URL with all migrations applied (the ingredients conftest
auto-applies 20260712_010000_recipe_docs.sql). recipe_docs is the
source-of-truth content table. The internal `_x` bookkeeping lives in its own
`x` column (never granted to anon), the portable RecipeGF recipe lives in `doc`
(that column IS the export), and the rendered source JSON-LD lives in `source`.
Column-level grants — mirroring 20260424054315_recipes_public_security_invoker —
keep `x` (and the internal generated keys) unreadable by anon even on a direct
table query, while the security_invoker recipes_public view preserves the current
public contract (id, source_url, site, name, author, image_url, jsonld).
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Json


def _row(**over) -> dict:
    """Column values for a fully-populated recipe_docs row."""
    r = {
        "source_url": "https://ex/negroni",
        # doc = the PORTABLE recipegf/cocktail/v1 recipe, no _x inside.
        "doc": {
            "schema": "recipegf/cocktail/v1",
            "id": "com.spiritolo/negroni:v1",
            "title": "Negroni",
            "ingredients": [{"name": "Campari", "ref": "spiritolo/campari"}],
            "steps": [],
            "equipment": [],
        },
        # source = raw Schema.org JSON-LD + display provenance (public).
        "source": {
            "jsonld": {
                "name": "Negroni",
                "author": "Punch Editorial",
                "image": "https://ex/negroni.jpg",
            },
            "jsonld_origin": "verbatim",
        },
        # x = internal-only sidecar (admin-only, never public, never exported).
        "x": {
            "site": "punch",
            "canonical_name": "Negroni",
            "cluster_key": "sha256:abc",
            "variant_key": "sha256:def",
            "jsonld_origin": "verbatim",
        },
        "name": "Negroni",
        "author": "Punch Editorial",
        "image_url": "https://ex/negroni.jpg",
        "state": "extracted",
    }
    r.update(over)
    return r


_COLS = ("source_url", "doc", "source", "x", "name", "author", "image_url", "state")


def _insert(conn, row: dict):
    vals = [Json(row[c]) if c in ("doc", "source", "x") else row[c] for c in _COLS]
    placeholders = ", ".join(["%s"] * len(_COLS))
    return conn.execute(
        f"insert into recipe_docs ({', '.join(_COLS)}) values ({placeholders}) "
        "returning id",
        vals,
    ).fetchone()[0]


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
    assert cols["id"][0] == "bigint"
    assert cols["id"][1] == "NO"
    assert cols["source_url"][:2] == ("text", "NO")

    # doc = portable recipe (not null); source = public raw JSON-LD (nullable);
    # x = internal sidecar (not null, defaults to '{}').
    assert cols["doc"][:2] == ("jsonb", "NO")
    assert cols["source"][:2] == ("jsonb", "YES")
    assert cols["x"][:2] == ("jsonb", "NO")
    assert "{}" in (cols["x"][2] or "")

    # doc_schema now names the RecipeGF schema the export validates against.
    assert cols["doc_schema"][:2] == ("text", "NO")
    assert "recipegf/cocktail/v1" in (cols["doc_schema"][2] or "")

    # Public scalar columns (populated by extract later; nullable now).
    for c in ("name", "author", "image_url"):
        assert cols[c][:2] == ("text", "YES"), c

    assert cols["state"][:2] == ("text", "NO")
    assert "extracted" in (cols["state"][2] or "")
    assert cols["updated_at"][:2] == ("timestamp with time zone", "NO")

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

    # generated projection columns: title from doc, the rest from x.
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
        _insert(db_conn, _row(state="bogus"))


def test_source_url_unique(db_conn):
    _reset_table(db_conn)
    _insert(db_conn, _row(source_url="https://ex/dup"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(db_conn, _row(source_url="https://ex/dup"))


# --------------------------------------------------------------------------
# Behavior — generated columns track doc/x
# --------------------------------------------------------------------------

def test_generated_columns_track_doc(db_conn):
    _reset_table(db_conn)
    doc_id = _insert(db_conn, _row(source_url="https://ex/gen"))

    row = db_conn.execute(
        "select title, site, canonical_name, cluster_key, variant_key "
        "from recipe_docs where id = %s",
        (doc_id,),
    ).fetchone()
    assert row == ("Negroni", "punch", "Negroni", "sha256:abc", "sha256:def")

    # Mutate doc (title) and x (the internal keys); generated columns follow.
    new_doc = dict(_row()["doc"])
    new_doc["title"] = "Boulevardier"
    new_x = {
        "site": "seriouseats",
        "canonical_name": "Boulevardier",
        "cluster_key": "sha256:zzz",
        "variant_key": "sha256:yyy",
    }
    db_conn.execute(
        "update recipe_docs set doc = %s, x = %s where id = %s",
        (Json(new_doc), Json(new_x), doc_id),
    )
    row = db_conn.execute(
        "select title, site, canonical_name, cluster_key, variant_key "
        "from recipe_docs where id = %s",
        (doc_id,),
    ).fetchone()
    assert row == (
        "Boulevardier", "seriouseats", "Boulevardier", "sha256:zzz", "sha256:yyy",
    )


# --------------------------------------------------------------------------
# Indexes — jsonb_path_ops GIN on doc + trgm, and the GIN is planner-usable
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

    # The @> containment query planner-uses the jsonb_path_ops GIN on doc.
    _reset_table(db_conn)
    _insert(
        db_conn,
        _row(
            source_url="https://ex/gin1",
            doc={
                "schema": "recipegf/cocktail/v1",
                "title": "Gin thing",
                "ingredients": [{"ref": "spiritolo/gin"}],
                "steps": [],
            },
        ),
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
# Boundary — RLS denies anon writes; column grants hide the x sidecar
# --------------------------------------------------------------------------

def test_rls_denies_anon_direct_write(db_conn):
    _reset_table(db_conn)
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute(
                "insert into recipe_docs (source_url, doc) values (%s, %s)",
                ("https://ex/anon-write", Json(_row()["doc"])),
            )
    finally:
        db_conn.execute("reset role")


def test_anon_column_grants_hide_x_sidecar(db_conn):
    # The whole point of the amendment: a direct anon read sees the public recipe
    # + source, but the internal x sidecar (and the internal-only generated keys)
    # is denied at the column-privilege level, so it cannot leak even on a direct
    # table query.
    _reset_table(db_conn)
    _insert(db_conn, _row(source_url="https://ex/grants"))

    db_conn.execute("set role anon")
    try:
        # Public columns are readable.
        pub = db_conn.execute(
            "select doc, source, site, name, author, image_url from recipe_docs"
        ).fetchone()
        assert pub is not None
        assert pub[0]["title"] == "Negroni"  # doc
        assert pub[2] == "punch"             # site (public generated col)

        # Internal columns are denied (no column grant).
        for col in ("x", "cluster_key", "canonical_name", "variant_key"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db_conn.execute(f"select {col} from recipe_docs")
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
    _insert(db_conn, _row(source_url="https://ex/pub"))

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
    assert name == "Negroni"
    assert author == "Punch Editorial"
    assert image_url == "https://ex/negroni.jpg"
    # jsonld is the rendered source JSON-LD (source -> 'jsonld').
    assert jsonld == {
        "name": "Negroni",
        "author": "Punch Editorial",
        "image": "https://ex/negroni.jpg",
    }
