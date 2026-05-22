"""DB-side tests for the proposal review RPCs.

The functions guard on public.is_admin(). The conftest stubs auth.uid()
to return null; _become(db, admin=...) overrides it locally.
"""
from __future__ import annotations

import json
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
        conn.execute("delete from taxonomy_aliases")
        conn.execute("delete from taxonomy_edges")
        conn.execute("delete from taxonomy_provenance")
        conn.execute("delete from taxonomy_proposals")
        conn.execute("delete from recipe_ingredients")
        conn.execute("delete from recipes")
        conn.execute("delete from taxonomy_nodes")
        conn.execute("delete from profiles")
        conn.execute("delete from auth.users")
        conn.commit()
        yield conn


def _become(conn, *, admin: bool) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, email) values (%s, %s)",
        (uid, f"{uid}@test"),
    )
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.commit()
    return uid


def _become_anon(conn) -> None:
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    conn.commit()


def _seed_recipe_with_ingredient(conn, *, name: str) -> tuple[int, int]:
    """Insert a recipe + one recipe_ingredients row whose normalized
    `name` matches `name`. Returns (recipe_id, ingredient_id)."""
    rid = conn.execute(
        "insert into recipes (source_url, site, jsonld, fetched_at) "
        "values (%s, 'punch', '{}'::jsonb, '2026-04-25T00:00:00Z') returning id",
        (f"https://example.com/{uuid.uuid4()}",),
    ).fetchone()[0]
    iid = conn.execute(
        "insert into recipe_ingredients "
        "  (recipe_id, position, raw_text, name, parse_status, parser_version) "
        "values (%s, 0, %s, %s, 'parsed', 'v-test') returning id",
        (rid, name, name),
    ).fetchone()[0]
    conn.commit()
    return rid, iid


def _make_proposal(conn, *, raw_string: str, parent_id: int | None,
                   slug: str = "lemon-zest",
                   display_name: str = "Lemon Zest",
                   mapper_version: str = "v-test",
                   candidates: list[dict] | None = None) -> int:
    pid = conn.execute(
        "insert into taxonomy_proposals "
        "  (raw_string, proposed_slug, proposed_display_name, "
        "   proposed_parent_id, candidates, mapper_version) "
        "values (%s, %s, %s, %s, %s::jsonb, %s) returning id",
        (raw_string, slug, display_name, parent_id,
         json.dumps(candidates or []), mapper_version),
    ).fetchone()[0]
    conn.commit()
    return pid


# ---------------------------------------------------------------------------
# apply_proposal_create
# ---------------------------------------------------------------------------

def test_create_inserts_node_edge_alias_provenance_and_resolves_rows(db):
    _become(db, admin=True)
    parent_id = db.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('citrus', 'Citrus') returning id"
    ).fetchone()[0]
    db.commit()
    _, iid = _seed_recipe_with_ingredient(db, name="lemon zest")
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=parent_id)

    new_id = db.execute(
        "select apply_proposal_create(%s, %s)", (pid, None)
    ).fetchone()[0]
    db.commit()

    # node created with proposed slug + display_name
    assert db.execute(
        "select slug, display_name from taxonomy_nodes where id = %s",
        (new_id,),
    ).fetchone() == ("lemon-zest", "Lemon Zest")
    # edge from proposed_parent to new node
    assert db.execute(
        "select count(*) from taxonomy_edges "
        "where parent_id = %s and child_id = %s",
        (parent_id, new_id),
    ).fetchone()[0] == 1
    # alias mapping raw_string -> new node
    assert db.execute(
        "select count(*) from taxonomy_aliases "
        "where alias = 'lemon zest' and node_id = %s", (new_id,),
    ).fetchone()[0] == 1
    # provenance row
    assert db.execute(
        "select source, raw_string from taxonomy_provenance where node_id = %s",
        (new_id,),
    ).fetchone() == ("llm-mapper", "lemon zest")
    # recipe_ingredients row resolved
    assert db.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where id = %s", (iid,),
    ).fetchone() == (new_id, "llm", "v-test")
    # proposal marked approved
    assert db.execute(
        "select status from taxonomy_proposals where id = %s", (pid,),
    ).fetchone()[0] == "approved"


def test_create_uses_slug_override_when_supplied(db):
    _become(db, admin=True)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None,
                         slug="lemon-zest")
    new_id = db.execute(
        "select apply_proposal_create(%s, %s)", (pid, "citrus-zest-lemon"),
    ).fetchone()[0]
    db.commit()
    assert db.execute(
        "select slug from taxonomy_nodes where id = %s", (new_id,),
    ).fetchone()[0] == "citrus-zest-lemon"


def test_create_rejects_non_admin(db):
    _become(db, admin=False)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select apply_proposal_create(%s, %s)", (pid, None))


def test_create_rejects_anonymous(db):
    _become_anon(db)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select apply_proposal_create(%s, %s)", (pid, None))


def test_create_errors_when_slug_already_exists(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('lemon-zest', 'Lemon Zest')"
    )
    db.commit()
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None,
                         slug="lemon-zest")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("select apply_proposal_create(%s, %s)", (pid, None))


def test_create_rejects_non_pending_proposal(db):
    _become(db, admin=True)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    db.execute(
        "update taxonomy_proposals set status = 'approved' where id = %s",
        (pid,),
    )
    db.commit()
    with pytest.raises(psycopg.Error):
        db.execute("select apply_proposal_create(%s, %s)", (pid, None))


# ---------------------------------------------------------------------------
# apply_proposal_map_to_existing
# ---------------------------------------------------------------------------

def test_map_to_existing_inserts_alias_and_resolves_rows(db):
    _become(db, admin=True)
    node_id = db.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('lemon-peel', 'Lemon Peel') returning id"
    ).fetchone()[0]
    db.commit()
    _, iid = _seed_recipe_with_ingredient(db, name="lemon zest")
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)

    db.execute(
        "select apply_proposal_map_to_existing(%s, %s)", (pid, node_id),
    )
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_aliases "
        "where alias = 'lemon zest' and node_id = %s", (node_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where id = %s", (iid,),
    ).fetchone() == (node_id, "llm")
    assert db.execute(
        "select status from taxonomy_proposals where id = %s", (pid,),
    ).fetchone()[0] == "approved"


def test_map_to_existing_alias_insert_is_idempotent(db):
    _become(db, admin=True)
    node_id = db.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('lemon-peel', 'Lemon Peel') returning id"
    ).fetchone()[0]
    db.execute(
        "insert into taxonomy_aliases (alias, node_id) values ('lemon zest', %s)",
        (node_id,),
    )
    db.commit()
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)

    db.execute(
        "select apply_proposal_map_to_existing(%s, %s)", (pid, node_id),
    )
    db.commit()
    assert db.execute(
        "select count(*) from taxonomy_aliases "
        "where alias = 'lemon zest' and node_id = %s", (node_id,),
    ).fetchone()[0] == 1


def test_map_to_existing_errors_when_node_missing(db):
    _become(db, admin=True)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "select apply_proposal_map_to_existing(%s, %s)", (pid, 99999),
        )


def test_map_to_existing_rejects_non_admin(db):
    _become(db, admin=False)
    node_id = db.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values ('lemon-peel', 'Lemon Peel') returning id"
    ).fetchone()[0]
    db.commit()
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "select apply_proposal_map_to_existing(%s, %s)", (pid, node_id),
        )


# ---------------------------------------------------------------------------
# apply_proposal_flag
# ---------------------------------------------------------------------------

def test_flag_writes_reason_and_marks_proposal_flagged(db):
    _become(db, admin=True)
    _, iid = _seed_recipe_with_ingredient(db, name="lemon zest")
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)

    db.execute(
        "select apply_proposal_flag(%s, %s)", (pid, "ambiguous: zest vs juice?"),
    )
    db.commit()

    assert db.execute(
        "select flag_reason from recipe_ingredients where id = %s", (iid,),
    ).fetchone()[0] == "ambiguous: zest vs juice?"
    assert db.execute(
        "select status from taxonomy_proposals where id = %s", (pid,),
    ).fetchone()[0] == "flagged"


def test_flag_rejects_empty_reason(db):
    _become(db, admin=True)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.Error):
        db.execute("select apply_proposal_flag(%s, %s)", (pid, "   "))


def test_flag_rejects_non_admin(db):
    _become(db, admin=False)
    pid = _make_proposal(db, raw_string="lemon zest", parent_id=None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select apply_proposal_flag(%s, %s)", (pid, "later"))
