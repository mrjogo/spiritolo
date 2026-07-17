"""Spine tests for the unified stage-review layer: schema constraints,
append-versioned ledger, apply_review() per stage, needs_review view, the review
model, and the re-apply/supersede overlay. DB-integration (TEST_DB_URL)."""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.types.json import Json

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DB_URL"), reason="no TEST_DB_URL"
)

_TABLES = (
    "stage_reviews", "stage_runs", "recipe_ingredients", "recipe_steps",
    "ingredient_resolutions", "recipes",
)


@pytest.fixture
def clean(db_conn):
    for t in _TABLES:
        db_conn.execute(f"truncate table {t} restart identity cascade")
    db_conn.execute("delete from stage_live_version")
    return db_conn


def _recipe(conn, url="u1"):
    return conn.execute(
        "insert into recipes (source_url, site) values (%s, 't') returning id", (url,)
    ).fetchone()[0]


def _review(conn, **kw):
    kw.setdefault("origin", "human_flag")
    cols = ", ".join(kw)
    vals = ", ".join(["%s"] * len(kw))
    return conn.execute(
        f"insert into stage_reviews ({cols}) values ({vals}) returning id",
        tuple(kw.values()),
    ).fetchone()[0]


# --- schema: one-open constraint -------------------------------------------

def test_one_open_review_per_entity_stage(clean):
    _review(clean, entity_kind="ingredient_name", entity_id="lime", stage="map")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _review(clean, entity_kind="ingredient_name", entity_id="lime", stage="map",
                origin="machine_proposal")


def test_resolved_row_does_not_block_new_open(clean):
    _review(clean, entity_kind="ingredient_name", entity_id="gin", stage="map",
            state="resolved")
    _review(clean, entity_kind="ingredient_name", entity_id="gin", stage="map")  # ok


# --- append-versioned ledger + live pointer --------------------------------

def test_ledger_appends_versions(clean):
    from ingredients.pipeline import ledger
    rid = _recipe(clean)
    ledger.record_run(clean, entity_type="recipe", entity_id=rid, stage="map",
                      version="v1", outcome="resolved", method="deterministic")
    ledger.record_run(clean, entity_type="recipe", entity_id=rid, stage="map",
                      version="v2", outcome="resolved", method="deterministic")
    n = clean.execute(
        "select count(*) from stage_runs where entity_id=%s and stage='map'", (rid,)
    ).fetchone()[0]
    assert n == 2


def test_same_version_rerun_overwrites(clean):
    from ingredients.pipeline import ledger
    rid = _recipe(clean)
    ledger.record_run(clean, entity_type="recipe", entity_id=rid, stage="map",
                      version="v1", outcome="pending", method="deterministic")
    ledger.record_run(clean, entity_type="recipe", entity_id=rid, stage="map",
                      version="v1", outcome="resolved", method="deterministic")
    rows = clean.execute(
        "select outcome from stage_runs where entity_id=%s and stage='map'", (rid,)
    ).fetchall()
    assert rows == [("resolved",)]


def test_set_live_version(clean):
    from ingredients.pipeline import ledger
    ledger.set_live_version(clean, stage="map", version="v2")
    ledger.set_live_version(clean, stage="map", version="v3")
    v = clean.execute(
        "select version from stage_live_version where stage='map'"
    ).fetchone()[0]
    assert v == "v3"


# --- apply_review() per stage ----------------------------------------------

def test_apply_review_map(clean):
    rid = _review(clean, entity_kind="ingredient_name", entity_id="fresh lime juice",
                  stage="map", state="resolved", payload=Json({"slug": "lime-juice"}))
    clean.execute("select apply_review(%s)", (rid,))
    row = clean.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name='fresh lime juice'"
    ).fetchone()
    assert row == ("lime-juice", "manual")


def test_apply_review_parse_by_position(clean):
    r = _recipe(clean)
    clean.execute(
        "insert into recipe_ingredients(recipe_id,position,raw_text,name,unit) "
        "values (%s,0,'1 oz gin','gin','oz')", (r,)
    )
    rid = _review(clean, entity_kind="recipe_ingredient", entity_id=f"{r}:0",
                  stage="parse", state="resolved",
                  payload=Json({"name": "London gin", "unit": "ml"}))
    clean.execute("select apply_review(%s)", (rid,))
    row = clean.execute(
        "select name, unit from recipe_ingredients where recipe_id=%s and position=0", (r,)
    ).fetchone()
    assert row == ("London gin", "ml")


def test_apply_review_convert_replaces_steps(clean):
    r = _recipe(clean)
    clean.execute(
        "insert into recipe_steps(recipe_id,step_index,verb,result) values (%s,0,'old','x')",
        (r,)
    )
    payload = {"steps": [
        {"verb": "stir", "result": "mixture", "roles": {"input": ["gin"]},
         "modifiers": ["gently"]},
        {"verb": "strain", "result": "drink"},
    ]}
    rid = _review(clean, entity_kind="recipe", entity_id=str(r), stage="convert",
                  state="resolved", payload=Json(payload))
    clean.execute("select apply_review(%s)", (rid,))
    rows = clean.execute(
        "select step_index, verb, result, modifiers from recipe_steps "
        "where recipe_id=%s order by step_index", (r,)
    ).fetchall()
    assert [x[1] for x in rows] == ["stir", "strain"]
    assert rows[0][3] == ["gently"]


def test_apply_review_extract_updates_header(clean):
    r = _recipe(clean)
    rid = _review(clean, entity_kind="recipe", entity_id=str(r), stage="extract",
                  state="resolved", payload=Json({"title": "Real Negroni"}))
    clean.execute("select apply_review(%s)", (rid,))
    title = clean.execute("select title from recipes where id=%s", (r,)).fetchone()[0]
    assert title == "Real Negroni"


def test_apply_review_ignores_unresolved(clean):
    # an OPEN review must not materialize
    rid = _review(clean, entity_kind="ingredient_name", entity_id="x", stage="map",
                  payload=Json({"slug": "should-not-apply"}))
    clean.execute("select apply_review(%s)", (rid,))
    n = clean.execute("select count(*) from ingredient_resolutions").fetchone()[0]
    assert n == 0


# --- needs_review view ------------------------------------------------------

def test_needs_review_surfaces_open_and_abstain(clean):
    from ingredients.pipeline import ledger
    r = _recipe(clean)
    _review(clean, entity_kind="ingredient_name", entity_id="amaro", stage="map",
            origin="distance_gate")
    ledger.record_run(clean, entity_type="recipe", entity_id=r, stage="map",
                      version="v1", outcome="abstain", method="deterministic")
    ledger.set_live_version(clean, stage="map", version="v1")
    reasons = {x[0] for x in clean.execute("select reason from needs_review").fetchall()}
    assert "distance_gate" in reasons and "abstain" in reasons


def test_needs_review_ignores_nonlive_version(clean):
    from ingredients.pipeline import ledger
    r = _recipe(clean)
    ledger.record_run(clean, entity_type="recipe", entity_id=r, stage="map",
                      version="v1", outcome="abstain", method="deterministic")
    ledger.record_run(clean, entity_type="recipe", entity_id=r, stage="map",
                      version="v2", outcome="resolved", method="deterministic")
    ledger.set_live_version(clean, stage="map", version="v2")
    reasons = [x[0] for x in clean.execute(
        "select reason from needs_review where stage='map'").fetchall()]
    assert "abstain" not in reasons


# --- review model -----------------------------------------------------------

def test_insert_review_idempotent_open(clean):
    from ingredients.reviews import model
    a = model.insert_review(clean, entity_kind="ingredient_name", entity_id="gin",
                            stage="map", origin="human_flag")
    b = model.insert_review(clean, entity_kind="ingredient_name", entity_id="gin",
                            stage="map", origin="machine_proposal")
    assert a == b
    n = clean.execute("select count(*) from stage_reviews where entity_id='gin'").fetchone()[0]
    assert n == 1


def test_resolved_override_ids_exact_and_prefix(clean):
    from ingredients.reviews import model
    _review(clean, entity_kind="recipe", entity_id="5", stage="convert", state="resolved")
    _review(clean, entity_kind="recipe_ingredient", entity_id="5:2", stage="parse",
            state="resolved")
    assert len(model.resolved_override_ids(clean, stage="convert", ids=["5"])) == 1
    assert len(model.resolved_override_ids(clean, stage="parse", ids=["5"])) == 1  # prefix


# --- re-apply + supersede ---------------------------------------------------

def test_reapply_restamps_override(clean):
    from ingredients.reviews.reapply import reapply_overrides
    _review(clean, entity_kind="ingredient_name", entity_id="fresh lime juice",
            stage="map", state="resolved", payload=Json({"slug": "lime-juice"}))
    clean.execute(
        "insert into ingredient_resolutions(normalized_name,taxonomy_slug,method,version) "
        "values ('fresh lime juice','WRONG','lexical','v2')"
    )
    reapply_overrides(clean, stage="map", ids=["fresh lime juice"])
    slug = clean.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name='fresh lime juice'"
    ).fetchone()[0]
    assert slug == "lime-juice"


def test_supersede_dismisses_machine_not_human(clean):
    from ingredients.reviews.reapply import supersede_stale
    _review(clean, entity_kind="ingredient_name", entity_id="amaro", stage="map",
            origin="machine_proposal")
    _review(clean, entity_kind="ingredient_name", entity_id="suze", stage="map",
            origin="human_flag")
    n = supersede_stale(clean, stage="map", ids=["amaro", "suze"])
    assert n == 1
    m = clean.execute("select state from stage_reviews where entity_id='amaro'").fetchone()[0]
    h = clean.execute("select state from stage_reviews where entity_id='suze'").fetchone()[0]
    assert m == "dismissed" and h == "open"
