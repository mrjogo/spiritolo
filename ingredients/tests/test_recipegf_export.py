"""Export orchestration routing (exported vs parked, files, dry-run gating).

Pure-Python: the DB access layer and proposal writer are stubbed, so this
verifies ``run_export``'s control flow without a live Postgres. The relational
persistence + bundle generation in ``recipegf/db.py`` is covered against real
Postgres by test_recipegf_export_db.py.
"""

from __future__ import annotations

import json

import pytest

from ingredients.recipegf import export as export_mod
from ingredients.recipegf.converter import Ok, SourceIngredient, SourceRecipe

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"

_CANNED_BUNDLE = {
    "recipe": {"schema": "recipegf/cocktail/v1", "id": "com.spiritolo/old-fashioned:v1",
               "title": "Old Fashioned", "ingredients": [], "equipment": [], "steps": []},
    "verbs": [],
    "meta": {"slug": "old-fashioned", "source": "https://ex/of", "imported_at": _IMPORTED_AT},
}


def _stir_recipe():
    return SourceRecipe(
        canonical_name="Old Fashioned", source_url="https://ex/of",
        jsonld={"recipeInstructions": "Stir with ice and strain over a cube."},
        ingredients=[
            SourceIngredient(position=1, raw_text="2 oz bourbon", name="bourbon",
                             slug="bourbon", amount=2, unit="oz", role="base_spirit"),
            SourceIngredient(position=2, raw_text="1 cube ice", name="ice",
                             slug="ice", amount=1, unit="cube", role="ice"),
        ],
    )


def _muddle_recipe():
    return SourceRecipe(
        canonical_name="Mojito", source_url="https://ex/moj",
        jsonld={"recipeInstructions": "Muddle mint, add rum, stir."},
        ingredients=[
            SourceIngredient(position=1, raw_text="2 oz rum", name="rum",
                             slug="white-rum", amount=2, unit="oz", role="base_spirit"),
        ],
    )


class _FakeConn:
    def commit(self):
        pass


@pytest.fixture
def wired(monkeypatch):
    """Wire run_export to two clusters (one exportable, one muddle) and capture
    every DB-facing call."""
    queue = [
        {"cluster_id": 1, "canonical_name": "Old Fashioned",
         "representative_recipe_id": 11, "source_url": "https://ex/of", "jsonld": {}},
        {"cluster_id": 2, "canonical_name": "Mojito",
         "representative_recipe_id": 22, "source_url": "https://ex/moj", "jsonld": {}},
    ]
    sources = {11: _stir_recipe(), 22: _muddle_recipe()}
    calls = {"write_recipe": [], "park": [], "enqueue": []}

    monkeypatch.setattr(export_mod.export_db, "fetch_export_queue",
                        lambda conn, **kw: queue)
    monkeypatch.setattr(export_mod.export_db, "build_source_recipe",
                        lambda conn, row: sources[row["representative_recipe_id"]])
    monkeypatch.setattr(export_mod.export_db, "write_recipe",
                        lambda conn, **kw: calls["write_recipe"].append(kw) or 1)
    monkeypatch.setattr(export_mod.export_db, "park_uncertain",
                        lambda conn, **kw: calls["park"].append(kw))
    monkeypatch.setattr(export_mod.export_db, "generate_bundle",
                        lambda conn, **kw: _CANNED_BUNDLE if kw["cluster_id"] == 1 else None)
    monkeypatch.setattr(export_mod, "enqueue_proposal",
                        lambda conn, **kw: calls["enqueue"].append(kw) or 1)
    return calls


def test_routes_exported_and_uncertain(wired):
    counts = export_mod.run_export(_FakeConn(), imported_at=_IMPORTED_AT)
    assert counts["exported"] == 1
    assert counts["muddle_unsupported"] == 1

    assert len(wired["write_recipe"]) == 1
    written = wired["write_recipe"][0]
    assert written["cluster_id"] == 1
    assert written["result"].slug == "old-fashioned"
    assert written["result"].recipe["id"] == "com.spiritolo/old-fashioned:v1"

    assert len(wired["park"]) == 1 and wired["park"][0]["cluster_id"] == 2
    assert len(wired["enqueue"]) == 1
    assert wired["enqueue"][0]["reason"] == "muddle_unsupported"
    assert wired["enqueue"][0]["cluster_id"] == 2


def test_dry_run_writes_nothing(wired):
    counts = export_mod.run_export(_FakeConn(), imported_at=_IMPORTED_AT, dry_run=True)
    # Outcomes are still counted...
    assert counts["exported"] == 1 and counts["muddle_unsupported"] == 1
    # ...but no DB writes happen.
    assert wired["write_recipe"] == []
    assert wired["park"] == []
    assert wired["enqueue"] == []


def test_out_dir_writes_bundle_generated_from_store(wired, tmp_path):
    export_mod.run_export(_FakeConn(), imported_at=_IMPORTED_AT, out_dir=tmp_path)
    written = tmp_path / "old-fashioned.json"
    assert written.exists()
    # The emitted file is what generate_bundle (the store projection) returned.
    assert json.loads(written.read_text()) == _CANNED_BUNDLE
    assert list(tmp_path.glob("*.json")) == [written]
