"""Phase 3.1 mechanics for the two taxonomy harmonization stages.

Exercises the shared SQL primitives (`combine_merge`, `connect_place`), their
`apply_review` dispatch via `resolve_review`, and the `node_queue` work-queue
helper. DB-integration (TEST_DB_URL).
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Json

from ingredients.pipeline import ledger
from ingredients.pipeline.stages.base import node_queue

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DB_URL"), reason="no TEST_DB_URL"
)

STAGE_COMBINE = "combine-nodes"
STAGE_CONNECT = "connect-nodes"
_VERSION = "t1"

_TABLES = (
    "human_reviews", "job_items", "ingredient_resolutions", "taxonomy_nodes",
)


@pytest.fixture
def conn(test_db_url: str):
    """Autocommit connection with the taxonomy + queue tables truncated."""
    c = psycopg.connect(test_db_url, autocommit=True)
    for t in _TABLES:
        c.execute(f"truncate table {t} restart identity cascade")
    yield c
    for t in _TABLES:
        c.execute(f"truncate table {t} restart identity cascade")
    c.close()


def _node(conn, slug, *, status="live", node_kind=None, is_cluster_node=False):
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status, node_kind, is_cluster_node) "
        "values (%s, %s, %s, %s, %s) returning id",
        (slug, slug.replace("-", " ").title(), status, node_kind, is_cluster_node),
    ).fetchone()[0]


def _edge(conn, parent_id, child_id):
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (parent_id, child_id),
    )


def _alias(conn, node_id, alias):
    conn.execute(
        "insert into taxonomy_aliases (alias, node_id) values (%s, %s)", (alias, node_id)
    )


def _resolution(conn, name, slug):
    conn.execute(
        "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method) "
        "values (%s, %s, 'provisional')",
        (name, slug),
    )


# --- combine_merge ----------------------------------------------------------

def test_combine_merge_repoints_and_deletes_absorbed(conn):
    parent = _node(conn, "spirit")
    survivor = _node(conn, "angostura-bitters")
    absorbed = _node(conn, "angostura", status="provisional")
    _edge(conn, parent, absorbed)                 # parent -> absorbed
    _alias(conn, absorbed, "ango")                # an alias on the absorbed node
    _resolution(conn, "angostura bitters", "angostura")  # resolution -> absorbed slug

    conn.execute("select combine_merge(%s, %s)", (survivor, absorbed))

    # Resolution repointed to the survivor's slug.
    assert conn.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name='angostura bitters'"
    ).fetchone()[0] == "angostura-bitters"

    # Edge repointed: parent -> survivor now exists, parent -> absorbed gone.
    assert conn.execute(
        "select count(*) from taxonomy_edges where parent_id=%s and child_id=%s",
        (parent, survivor),
    ).fetchone()[0] == 1
    assert conn.execute(
        "select count(*) from taxonomy_edges where child_id=%s", (absorbed,)
    ).fetchone()[0] == 0

    # Absorbed slug is now a survivor alias (so future map lookups follow).
    assert conn.execute(
        "select count(*) from taxonomy_aliases where node_id=%s and alias='angostura'",
        (survivor,),
    ).fetchone()[0] == 1

    # Absorbed node is gone.
    assert conn.execute(
        "select count(*) from taxonomy_nodes where id=%s", (absorbed,)
    ).fetchone()[0] == 0


def test_combine_merge_rejects_self_merge(conn):
    n = _node(conn, "gin")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("select combine_merge(%s, %s)", (n, n))


# --- connect_place ----------------------------------------------------------

def test_connect_place_attaches_and_promotes(conn):
    parent = _node(conn, "bitters")
    node = _node(conn, "orange-bitters", status="provisional")

    conn.execute("select connect_place(%s, %s, %s, %s)", (node, "brand", ["bitters"], False))

    assert conn.execute(
        "select count(*) from taxonomy_edges where parent_id=%s and child_id=%s",
        (parent, node),
    ).fetchone()[0] == 1
    row = conn.execute(
        "select node_kind, status, is_cluster_node from taxonomy_nodes where id=%s", (node,)
    ).fetchone()
    assert row == ("brand", "live", False)


def test_connect_place_missing_parent_slug_raises(conn):
    node = _node(conn, "mystery", status="provisional")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("select connect_place(%s, %s, %s, %s)", (node, "brand", ["nope"], False))


def test_connect_place_antichain_violation_raises(conn):
    cluster = _node(conn, "bourbon", is_cluster_node=True)
    node = _node(conn, "makers-mark", status="provisional")
    # Making `node` a cluster node under a cluster ancestor violates the antichain.
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "select connect_place(%s, %s, %s, %s)", (node, "brand", ["bourbon"], True)
        )
    # And nothing was promoted (the raise rolls the statement back).
    assert conn.execute(
        "select status from taxonomy_nodes where id=%s", (node,)
    ).fetchone()[0] == "provisional"


def test_connect_place_antichain_rejects_cluster_descendant(conn):
    # The guard is two-sided: a node can't become a cluster node ABOVE an existing
    # cluster node either (that would give the descendant a cluster ancestor).
    parent = _node(conn, "spirits")
    node = _node(conn, "mid-node", status="provisional")
    child_cluster = _node(conn, "bourbon", is_cluster_node=True)
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (node, child_cluster),
    )
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "select connect_place(%s, %s, %s, %s)", (node, None, ["spirits"], True)
        )
    assert conn.execute(
        "select status from taxonomy_nodes where id=%s", (node,)
    ).fetchone()[0] == "provisional"


# --- apply_review dispatch via resolve_review -------------------------------

@pytest.fixture
def admin_conn(test_db_url: str):
    """Non-autocommit connection authenticated as an admin (auth.uid() rewired),
    with taxonomy + review tables cleaned. Restores auth.uid()->null on teardown
    so the stub doesn't leak into other tests."""
    c = psycopg.connect(test_db_url, autocommit=False)
    for t in (*_TABLES, "taxonomy_edges", "taxonomy_aliases"):
        c.execute(f"truncate table {t} restart identity cascade")
    c.execute("delete from profiles")
    c.execute("delete from auth.users")
    uid = uuid.uuid4()
    c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    c.execute("update profiles set is_admin = true where id = %s", (uid,))
    c.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    c.commit()
    yield c
    c.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    c.commit()
    c.close()


def _open_review(conn, *, stage, entity_id, payload):
    return conn.execute(
        "insert into human_reviews (entity_kind, entity_id, stage, origin, state, payload) "
        "values ('taxonomy_node', %s, %s, 'machine_proposal', 'open', %s) returning id",
        (entity_id, stage, Json(payload)),
    ).fetchone()[0]


def test_resolve_review_combine_merges(admin_conn):
    survivor = _node(admin_conn, "peychauds-bitters")
    absorbed = _node(admin_conn, "peychaud", status="provisional")
    _resolution(admin_conn, "peychauds", "peychaud")
    rid = _open_review(
        admin_conn,
        stage=STAGE_COMBINE,
        entity_id=str(absorbed),
        payload={"survivor_id": survivor, "absorbed_id": absorbed},
    )
    admin_conn.execute("select resolve_review(%s)", (rid,))

    assert admin_conn.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name='peychauds'"
    ).fetchone()[0] == "peychauds-bitters"
    assert admin_conn.execute(
        "select count(*) from taxonomy_nodes where id=%s", (absorbed,)
    ).fetchone()[0] == 0


def test_resolve_review_connect_places(admin_conn):
    _node(admin_conn, "liqueur")
    node = _node(admin_conn, "curacao", status="provisional")
    rid = _open_review(
        admin_conn,
        stage=STAGE_CONNECT,
        entity_id=str(node),
        payload={"node_kind": "brand", "parent_slugs": ["liqueur"], "is_cluster_node": False},
    )
    admin_conn.execute("select resolve_review(%s)", (rid,))

    row = admin_conn.execute(
        "select node_kind, status from taxonomy_nodes where id=%s", (node,)
    ).fetchone()
    assert row == ("brand", "live")
    assert admin_conn.execute(
        "select count(*) from taxonomy_edges e join taxonomy_nodes p on p.id=e.parent_id "
        "where e.child_id=%s and p.slug='liqueur'",
        (node,),
    ).fetchone()[0] == 1


# --- node_queue -------------------------------------------------------------

def test_node_queue_provisional_default_and_broad(conn):
    p1 = _node(conn, "prov-one", status="provisional")
    p2 = _node(conn, "prov-two", status="provisional")
    live = _node(conn, "live-one", status="live")
    # p1 already has a run row at (stage, version); it should drop out of both queues.
    ledger.record_run(
        conn, entity_type="taxonomy_node", entity_id=p1, stage=STAGE_COMBINE,
        version=_VERSION, outcome="resolved", method="deterministic",
    )

    default_ids = node_queue(conn, stage=STAGE_COMBINE, version=_VERSION)
    assert default_ids == [p2]                       # provisional-only, p1 excluded

    broad_ids = node_queue(conn, stage=STAGE_COMBINE, version=_VERSION, broad=True)
    assert set(broad_ids) == {p2, live}              # live node included, p1 still excluded
    assert p1 not in broad_ids

    # A newer version re-queues p1 (NOT-EXISTS keys on the current version).
    assert p1 in node_queue(conn, stage=STAGE_COMBINE, version="t2")
