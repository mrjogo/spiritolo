"""Parity tests for the stage_reviews backfill (20260724090000).

The migration runs at conftest bootstrap over an empty DB (a no-op there), so
these tests seed the source tables and run the same INSERT…SELECT statements to
validate the row mapping. DB-integration (TEST_DB_URL)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DB_URL"), reason="no TEST_DB_URL"
)

# Mirrors 20260724090000_stage_reviews_backfill.sql (statements 1 and 3).
_TP_TO_REVIEWS = """
insert into stage_reviews
    (entity_kind, entity_id, stage, state, origin, payload, origin_version,
     reviewed_by, reviewed_at, created_at)
select 'ingredient_name', tp.raw_string, 'map',
    case tp.status when 'pending' then 'open'
                   when 'approved' then 'resolved'
                   when 'rejected' then 'dismissed' end,
    'machine_proposal',
    jsonb_build_object('kind','form','proposed_slug',tp.proposed_slug,
        'proposed_display_name',tp.proposed_display_name,
        'proposed_parent_id',tp.proposed_parent_id,'candidates',tp.candidates),
    tp.mapper_version, tp.decided_by, tp.decided_at, tp.created_at
from taxonomy_proposals tp
on conflict (entity_kind, entity_id, stage) where state = 'open' do nothing
"""

_MANUAL_TO_REVIEWS = """
insert into stage_reviews
    (entity_kind, entity_id, stage, state, origin, payload, created_at)
select 'ingredient_name', ir.normalized_name, 'map', 'resolved', 'human_flag',
    jsonb_build_object('slug', ir.taxonomy_slug), ir.created_at
from ingredient_resolutions ir
where ir.method = 'manual' and ir.taxonomy_slug is not null
on conflict do nothing
"""


@pytest.fixture
def clean(db_conn):
    for t in ("stage_reviews", "taxonomy_proposals", "ingredient_resolutions"):
        db_conn.execute(f"truncate table {t} restart identity cascade")
    return db_conn


def test_taxonomy_proposals_backfill_maps_state_and_payload(clean):
    clean.execute(
        "insert into taxonomy_proposals"
        "(raw_string,proposed_slug,proposed_display_name,proposed_parent_id,"
        "candidates,mapper_version,status) "
        "values ('lemon zest','lemon-zest','Lemon Zest',null,'[]'::jsonb,'v1','pending')"
    )
    clean.execute(
        "insert into taxonomy_proposals"
        "(raw_string,proposed_slug,proposed_display_name,proposed_parent_id,"
        "candidates,mapper_version,status,decided_by,decided_at) "
        "values ('lime oil','lime-oil','Lime Oil',null,'[]'::jsonb,'v1','approved','alice',now())"
    )
    clean.execute(_TP_TO_REVIEWS)

    rows = dict(
        clean.execute(
            "select entity_id, state from stage_reviews "
            "where stage='map' and origin='machine_proposal'"
        ).fetchall()
    )
    assert rows == {"lemon zest": "open", "lime oil": "resolved"}
    slug = clean.execute(
        "select payload->>'proposed_slug' from stage_reviews where entity_id='lemon zest'"
    ).fetchone()[0]
    assert slug == "lemon-zest"


def test_manual_backfill_only_manual_resolved(clean):
    clean.execute(
        "insert into ingredient_resolutions(normalized_name,taxonomy_slug,method,version) "
        "values ('fresh lime juice','lime-juice','manual','v1')"
    )
    clean.execute(
        "insert into ingredient_resolutions(normalized_name,taxonomy_slug,method,version) "
        "values ('gin','london-dry-gin','lexical','v1')"  # not manual -> skipped
    )
    clean.execute(_MANUAL_TO_REVIEWS)

    rows = clean.execute(
        "select entity_id, state, origin, payload->>'slug' from stage_reviews where stage='map'"
    ).fetchall()
    assert rows == [("fresh lime juice", "resolved", "human_flag", "lime-juice")]
