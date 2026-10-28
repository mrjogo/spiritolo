"""The headless smoke runner: real runs through runner.run_job, scripted model."""
from __future__ import annotations

import gzip
import json

from common.llm.provider import ProviderResult
from common.providers import packing

from ingredients import smoke
from ingredients.pipeline import ledger
from ingredients.pipeline.corpus import CorpusMiss
from ingredients.pipeline.stages import extract
from ingredients.worker.providers import ProviderChain


class _Model:
    """Answers every item of a packed call: map picks the first candidate,
    extract finds a one-ingredient recipe."""

    cost_per_call = 1

    def resolve(self, *, system_prompt, user_prompt, response_schema=None):
        rows = []
        for it in json.loads(user_prompt)["items"]:
            inp = it["input"]
            if "candidates" in inp:
                ans = {"action": "chose_slug", "slug": inp["candidates"][0]["slug"]}
            else:
                ans = {"found": True, "name": "Daiquiri", "recipeIngredient": ["2 oz rum"],
                       "recipeInstructions": ["Shake."], "description": None,
                       "recipeYield": None}
            rows.append({"id": it["id"], "answer": ans})
        return ProviderResult(packing.encode_response(rows), "m")


class _Corpus:
    def read_html(self, key):
        if key != "k1":
            raise CorpusMiss(key)
        return "<h1>Daiquiri</h1><li>2 oz rum</li>"


def _seed(conn):
    conn.execute("insert into taxonomy_nodes (slug, display_name) values ('amaro', 'Amaro')")
    rid = conn.execute(
        "insert into recipes (source_url, site, source) values ('https://ex/r', 'ex', '{}') "
        "returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
        "values (?, 0, 'Fancy Amaro', 'x')", (rid,),
    )
    conn.execute(
        "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
        "values ('fancy amaro', 'fancy-amaro', 'provisional', 'v2')"
    )
    pid = conn.execute(
        "insert into pages (url, site, corpus_key, content_type) "
        "values ('https://ex/p', 'ex', 'k1', 'likely_drink_recipe') returning id"
    ).fetchone()[0]
    ledger.record_run(conn, entity_type="page", entity_id=pid, stage="extract-recipe",
                      version="v1", outcome="abstain", method="deterministic",
                      state="applied", job_id=None)


def test_smoke_runs_map_and_extract_and_reports(db_conn):
    _seed(db_conn)
    extract.set_corpus_reader(_Corpus())
    try:
        report = smoke.smoke(
            db_conn, provider="deepseek", n_map=5, n_extract=5, cap_cents=50,
            providers_builder=lambda job: ProviderChain(tiers=[("deepseek", _Model())], pack_size=10),
        )
    finally:
        extract.set_corpus_reader(None)

    assert "**done**" in report
    assert "fancy amaro → `amaro` (was provisional)" in report
    assert "https://ex/p → “Daiquiri”, 1 ingredients" in report
    assert db_conn.execute(
        "select method from ingredient_resolutions where normalized_name = 'fancy amaro'"
    ).fetchone()[0] == "llm"


def test_smoke_leaves_other_queued_runs_alone(db_conn):
    _seed(db_conn)
    other = db_conn.execute(
        "insert into jobs (stage, state) values ('map-ingredient', 'queued') returning id"
    ).fetchone()[0]
    smoke.smoke(db_conn, provider="deepseek", n_map=5, n_extract=0,
                providers_builder=lambda job: None)
    assert db_conn.execute("select state from jobs where id = ?", (other,)).fetchone()[0] == "queued"


def test_pick_extract_pages_prefers_confirmed_drinks(db_conn):
    ids = {}
    for url, ctype in (("https://ex/hub", "likely_drink_recipe"),
                       ("https://ex/recipe", "confirmed_drink")):
        ids[url] = db_conn.execute(
            "insert into pages (url, site, corpus_key, content_type) values (?, 'ex', ?, ?) "
            "returning id", (url, url, ctype),
        ).fetchone()[0]
        ledger.record_run(db_conn, entity_type="page", entity_id=ids[url],
                          stage="extract-recipe", version="v1", outcome="abstain",
                          method="deterministic", state="applied", job_id=None)

    assert smoke.pick_extract_pages(db_conn, 1) == [ids["https://ex/recipe"]]
    assert smoke.pick_extract_pages(db_conn, 2) == [ids["https://ex/recipe"], ids["https://ex/hub"]]
