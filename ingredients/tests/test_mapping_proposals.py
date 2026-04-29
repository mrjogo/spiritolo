import psycopg

from ingredients.mapping.proposals import (
    enqueue_form_proposal, fetch_pending_proposals, mark_decided,
)


def test_enqueue_writes_pending_row(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    pid = enqueue_form_proposal(
        conn,
        raw_string="lemon zest",
        proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest",
        proposed_parent_id=ids["lemon"],
        candidates=[{"node_id": ids["lemon_wheel"], "display_name": "Lemon Wheel", "similarity": 0.6}],
        mapper_version="v1",
    )
    row = conn.execute(
        "select raw_string, proposed_slug, status from taxonomy_proposals where id = %s",
        (pid,),
    ).fetchone()
    assert row == ("lemon zest", "lemon_zest", "pending")


def test_enqueue_is_idempotent_per_version(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    # Same string + same version: no duplicate row, returns existing id.
    pid2 = enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    assert conn.execute("select count(*) from taxonomy_proposals").fetchone()[0] == 1
    assert isinstance(pid2, int)


def test_fetch_pending_returns_only_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    pid = enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    enqueue_form_proposal(
        conn, raw_string="lime oil", proposed_slug="lime_oil",
        proposed_display_name="Lime Oil", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    mark_decided(conn, proposal_id=pid, status="rejected", decided_by="alice")
    pending = fetch_pending_proposals(conn)
    assert [p["raw_string"] for p in pending] == ["lime oil"]


def test_mark_decided_rejects_invalid_status(fixture_taxonomy):
    import pytest
    conn, _ = fixture_taxonomy
    with pytest.raises(ValueError):
        mark_decided(conn, proposal_id=1, status="maybe", decided_by="alice")
