"""Payload-shape tests for the audit log.

The log stores three shapes, by op:

- INSERT → ``after`` is NULL. The event is kept; the payload is dropped as
  redundant (see the reconstruction invariant below).
- UPDATE → ``before``/``after`` narrowed to the ``changed_keys`` subset.
- DELETE → ``before`` kept in full, closing the loop.

RECONSTRUCTION INVARIANT: the inserted value is recoverable as the current row
with each UPDATE's ``before`` image reverse-applied newest → oldest. This is
what makes dropping the INSERT payload safe, and it only holds while a row's
audit chain is unbroken — so no date-based retention may be added without
reinstating full INSERT payloads. ``test_insert_payload_is_reconstructable``
is the executable proof.

Runs against ``TEST_DB_URL``.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


@pytest.fixture
def clean(db_conn):
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    db_conn.execute("truncate table audit.log restart identity")
    db_conn.execute("delete from taxonomy_nodes")
    return db_conn


def _insert_node(conn, slug: str, name: str) -> int:
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
        (slug, name),
    ).fetchone()[0]


def _rows(conn, pk) -> list[dict]:
    """Every audit row for a taxonomy_nodes pk, oldest first."""
    cols = ["id", "op", "before", "after", "changed_keys"]
    res = conn.execute(
        f"select {', '.join(cols)} from audit.log "
        "where table_name = 'taxonomy_nodes' and pk = %s order by id",
        (str(pk),),
    ).fetchall()
    return [dict(zip(cols, r)) for r in res]


def test_insert_stores_event_without_payload(clean):
    conn = clean
    nid = _insert_node(conn, "mezcal", "Mezcal")

    (ins,) = _rows(conn, nid)
    assert ins["op"] == "I"
    assert ins["after"] is None, "INSERT payload is redundant and must not be stored"
    assert ins["before"] is None
    # The EVENT survives in full — only the payload is dropped.
    row = conn.execute(
        "select actor_kind, source, pk from audit.log where id = %s", (ins["id"],)
    ).fetchone()
    assert row[0] == "system"
    assert row[1]
    assert row[2] == str(nid)


def test_update_stores_only_changed_keys(clean):
    conn = clean
    nid = _insert_node(conn, "amaro", "Amaro")
    conn.execute("truncate table audit.log restart identity")

    conn.execute(
        "update taxonomy_nodes set display_name = 'Amaro Nonino' where id = %s", (nid,)
    )

    (upd,) = _rows(conn, nid)
    assert upd["op"] == "U"
    keys = set(upd["changed_keys"])
    assert keys == {"display_name", "updated_at"}, upd["changed_keys"]
    # before/after carry EXACTLY the changed keys — no slug, no id, no created_at.
    assert set(upd["before"]) == keys
    assert set(upd["after"]) == keys
    assert upd["before"]["display_name"] == "Amaro"
    assert upd["after"]["display_name"] == "Amaro Nonino"


def test_delete_keeps_full_before(clean):
    conn = clean
    nid = _insert_node(conn, "pisco", "Pisco")
    conn.execute("truncate table audit.log restart identity")

    conn.execute("delete from taxonomy_nodes where id = %s", (nid,))

    (dele,) = _rows(conn, nid)
    assert dele["op"] == "D"
    assert dele["after"] is None
    # Full image, not a subset — deletes close the reconstruction loop.
    assert dele["before"]["slug"] == "pisco"
    assert dele["before"]["display_name"] == "Pisco"
    assert "created_at" in dele["before"]


def test_noop_update_records_nothing_changed(clean):
    conn = clean
    nid = _insert_node(conn, "rhum", "Rhum")
    conn.execute("truncate table audit.log restart identity")

    # public.set_updated_at() writes now(), which is TRANSACTION-scoped — so
    # inside one transaction the second update writes an identical updated_at
    # and changes nothing at all. That is the only way to reach the empty
    # changed_keys path, which must leave before/after NULL rather than {}.
    with conn.transaction():
        conn.execute(
            "update taxonomy_nodes set display_name = 'Rum' where id = %s", (nid,)
        )
        conn.execute(
            "update taxonomy_nodes set display_name = 'Rum' where id = %s", (nid,)
        )

    rows = _rows(conn, nid)
    assert len(rows) == 2
    noop = rows[-1]
    assert noop["op"] == "U"
    assert not noop["changed_keys"]
    assert noop["before"] is None
    assert noop["after"] is None


def test_insert_payload_is_reconstructable(clean):
    """The executable proof of the reconstruction invariant.

    Insert, mutate repeatedly, then rebuild the original inserted row from the
    current state plus the stored UPDATE diffs alone — never reading the
    INSERT payload, which no longer exists.
    """
    conn = clean
    nid = _insert_node(conn, "cachaca", "Cachaca")
    original = conn.execute(
        "select to_jsonb(t.*) from taxonomy_nodes t where id = %s", (nid,)
    ).fetchone()[0]

    conn.execute(
        "update taxonomy_nodes set display_name = 'Cachaça' where id = %s", (nid,)
    )
    conn.execute(
        "update taxonomy_nodes set status = 'provisional' where id = %s", (nid,)
    )
    conn.execute(
        "update taxonomy_nodes set display_name = 'Cachaça (BR)' where id = %s", (nid,)
    )

    current = conn.execute(
        "select to_jsonb(t.*) from taxonomy_nodes t where id = %s", (nid,)
    ).fetchone()[0]

    # Reverse-apply each UPDATE's `before` image, newest → oldest.
    reconstructed = dict(current)
    for row in reversed(_rows(conn, nid)):
        if row["op"] == "U" and row["before"]:
            reconstructed.update(row["before"])

    assert reconstructed == original
