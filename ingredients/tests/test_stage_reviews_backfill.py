"""Parity test for the stage_reviews backfill (20260724090000).

The migration runs at conftest bootstrap over an empty DB (a no-op there), so
this seeds the source table and runs the same INSERT…SELECT to validate the row
mapping. (The taxonomy_proposals half of the backfill is no longer testable here
because a later migration drops that table; it was validated before the drop and
runs at migration-apply time.) DB-integration (TEST_DB_URL)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DB_URL"), reason="no TEST_DB_URL"
)

# Mirrors 20260724090000_stage_reviews_backfill.sql (statement 3).
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
    for t in ("stage_reviews", "ingredient_resolutions"):
        db_conn.execute(f"truncate table {t} restart identity cascade")
    return db_conn


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
