"""DB-side tests for the five taxonomy curation RPCs.

The functions guard on public.is_admin(), which reads
profiles.is_admin filtered by auth.uid(). The conftest stubs
auth.uid() to return null. Each test that needs an authenticated
admin overrides auth.uid() locally + inserts a profiles row.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


@pytest.fixture
def db():
    url = os.environ["TEST_DB_URL"]
    with psycopg.connect(url, autocommit=False) as conn:
        # leave migrations applied; clean only the rows we'll touch
        conn.execute("delete from taxonomy_aliases")
        conn.execute("delete from taxonomy_edges")
        conn.execute("delete from taxonomy_provenance")
        conn.execute("delete from human_reviews")
        conn.execute("delete from recipe_ingredients")
        conn.execute("delete from taxonomy_nodes")
        conn.execute("delete from profiles")
        conn.execute("delete from auth.users")
        conn.commit()
        yield conn


def _become(conn: psycopg.Connection, *, admin: bool) -> uuid.UUID:
    """Insert an auth.users + profiles row and rewire auth.uid() to it.

    Note: the on_auth_user_created trigger auto-inserts into profiles when
    auth.users gets a new row, so we update the trigger-created row rather
    than inserting a duplicate.
    """
    uid = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, email) values (%s, %s)",
        (uid, f"{uid}@test"),
    )
    # The trigger created the profiles row; update it to set is_admin.
    conn.execute(
        "update profiles set is_admin = %s where id = %s",
        (admin, uid),
    )
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.commit()
    return uid


def _become_anon(conn: psycopg.Connection) -> None:
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# create_taxonomy_node
# ---------------------------------------------------------------------------

def test_create_inserts_node_edge_aliases(db):
    _become(db, admin=True)
    parent_id = db.execute(
        "insert into taxonomy_nodes (slug, display_name) values ('amari', 'amari') returning id"
    ).fetchone()[0]
    db.commit()

    new_id = db.execute(
        "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
        (parent_id, "campari", "Campari", "brand", "modifier", True, False, ["campari aperitivo"]),
    ).fetchone()[0]
    db.commit()

    row = db.execute(
        "select slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish from taxonomy_nodes where id = %s",
        (new_id,),
    ).fetchone()
    assert row == ("campari", "Campari", "brand", "modifier", True, False)
    assert db.execute(
        "select count(*) from taxonomy_edges where parent_id = %s and child_id = %s",
        (parent_id, new_id),
    ).fetchone()[0] == 1
    assert sorted(
        r[0] for r in db.execute(
            "select alias from taxonomy_aliases where node_id = %s", (new_id,)
        ).fetchall()
    ) == ["campari aperitivo"]


def test_create_rejects_non_admin(db):
    _become(db, admin=False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
            (None, "x", "X", None, None, False, False, []),
        )


def test_create_rejects_anonymous(db):
    _become_anon(db)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
            (None, "x", "X", None, None, False, False, []),
        )


# ---------------------------------------------------------------------------
# update_taxonomy_node
# ---------------------------------------------------------------------------

def test_update_patches_only_listed_keys(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish) values "
        "(1, 'campari', 'Campari', 'brand', 'modifier', true, false)"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(%s, %s::jsonb)",
        (1, '{"display_name": "Campari Aperitivo"}'),
    )
    db.commit()

    row = db.execute(
        "select slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish from taxonomy_nodes where id = 1"
    ).fetchone()
    # Only display_name changed.
    assert row == ("campari", "Campari Aperitivo", "brand", "modifier", True, False)


def test_update_replaces_aliases_when_key_present(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'campari', 'Campari')"
    )
    db.execute(
        "insert into taxonomy_aliases (alias, node_id) values ('old1', 1), ('old2', 1)"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(%s, %s::jsonb)",
        (1, '{"aliases": ["new1", "new2", "new3"]}'),
    )
    db.commit()

    aliases = sorted(
        r[0] for r in db.execute(
            "select alias from taxonomy_aliases where node_id = 1"
        ).fetchall()
    )
    assert aliases == ["new1", "new2", "new3"]


def test_update_clears_aliases_with_empty_array(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'campari', 'Campari')"
    )
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('old', 1)")
    db.commit()

    db.execute("select update_taxonomy_node(1, '{\"aliases\": []}'::jsonb)")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_aliases where node_id = 1"
    ).fetchone()[0] == 0


def test_update_can_null_node_kind(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name, node_kind) "
        "values (1, 'x', 'X', 'brand')"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(1, '{\"node_kind\": null}'::jsonb)"
    )
    db.commit()

    assert db.execute(
        "select node_kind from taxonomy_nodes where id = 1"
    ).fetchone()[0] is None


def test_update_rejects_non_admin(db):
    _become(db, admin=False)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'x', 'X')"
    )
    db.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select update_taxonomy_node(1, '{}'::jsonb)")


# ---------------------------------------------------------------------------
# set_node_parents
# ---------------------------------------------------------------------------

def test_set_parents_replaces_edge_set(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C'),(4,'d','D')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 4), (2, 4)"
    )
    db.commit()

    db.execute("select set_node_parents(4, ARRAY[2, 3]::bigint[])")
    db.commit()

    parents = sorted(
        r[0] for r in db.execute(
            "select parent_id from taxonomy_edges where child_id = 4"
        ).fetchall()
    )
    assert parents == [2, 3]


def test_set_parents_rejects_self(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'a', 'A')"
    )
    db.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("select set_node_parents(1, ARRAY[1]::bigint[])")


def test_set_parents_rejects_descendant(db):
    _become(db, admin=True)
    # 1 → 2 → 3
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 2), (2, 3)"
    )
    db.commit()
    # Trying to make 3 a parent of 1 would create a cycle.
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("select set_node_parents(1, ARRAY[3]::bigint[])")


def test_set_parents_to_empty_clears(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.commit()

    db.execute("select set_node_parents(2, ARRAY[]::bigint[])")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_edges where child_id = 2"
    ).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# delete_taxonomy_node + get_taxonomy_node_blockers
# ---------------------------------------------------------------------------

def test_delete_succeeds_when_no_blockers(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('x', 2)")
    db.commit()

    db.execute("select delete_taxonomy_node(2)")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_nodes where id = 2"
    ).fetchone()[0] == 0
    # Cascade dropped the edge + alias.
    assert db.execute(
        "select count(*) from taxonomy_edges where child_id = 2"
    ).fetchone()[0] == 0
    assert db.execute(
        "select count(*) from taxonomy_aliases where node_id = 2"
    ).fetchone()[0] == 0


def test_delete_blocked_by_children(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("select delete_taxonomy_node(1)")


def test_blockers_report_all_dimensions(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 2), (1, 3)"
    )
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('x', 1)")
    db.commit()

    blockers = db.execute(
        "select get_taxonomy_node_blockers(1)"
    ).fetchone()[0]
    assert blockers["children"] == 2
    assert sorted(c["display_name"] for c in blockers["child_names"]) == ["B", "C"]
    assert blockers["aliases"] == 1
    assert blockers["parents"] == 0
    assert blockers["recipe_ingredients"] == 0
    assert blockers["form_proposals"] == 0

    # An open map form proposal naming this node as parent is a blocker.
    db.execute(
        "insert into human_reviews (entity_kind, entity_id, stage, origin, payload) "
        "values ('ingredient_name', 'zest of a', 'map-ingredient', 'machine_proposal', "
        "jsonb_build_object('kind','form','proposed_parent_id', 1))"
    )
    db.commit()
    blockers = db.execute("select get_taxonomy_node_blockers(1)").fetchone()[0]
    assert blockers["form_proposals"] == 1
