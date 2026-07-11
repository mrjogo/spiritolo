"""Spiritolo extension verb-defs + overlay registry. Pure-Python (no DB)."""

from __future__ import annotations

from recipegf import VerbRegistry, RecipeValidator

from ingredients.recipegf.verbs import (
    is_spiritolo_verb,
    overlay_registry,
    spiritolo_verb_defs,
    verb_defs_for,
)


def test_defs_are_self_describing_and_namespaced():
    defs = spiritolo_verb_defs()
    assert "spiritolo/blend" in defs
    assert "spiritolo/top" in defs
    for name, d in defs.items():
        assert d["verb"] == name                      # keyed by its own name
        assert name.startswith("spiritolo/")          # registered namespace
        assert d["roles"]                             # has role contract


def test_is_spiritolo_verb():
    assert is_spiritolo_verb("spiritolo/blend")
    assert not is_spiritolo_verb("stir")
    assert not is_spiritolo_verb("barbot/pour")


def test_verb_defs_for_filters_and_dedupes():
    # Only namespaced verbs travel in a bundle; core verbs are dropped.
    out = verb_defs_for(["stir", "spiritolo/blend", "add", "spiritolo/blend"])
    assert [d["verb"] for d in out] == ["spiritolo/blend"]
    assert verb_defs_for(["stir", "add"]) == []


def test_verb_defs_for_is_sorted():
    out = verb_defs_for(["spiritolo/top", "spiritolo/blend"])
    assert [d["verb"] for d in out] == ["spiritolo/blend", "spiritolo/top"]


def test_overlay_registry_has_core_and_spiritolo():
    reg = overlay_registry()  # all spiritolo defs
    assert reg.has("stir")            # core
    assert reg.has("spiritolo/blend")  # extension
    assert reg.has("spiritolo/top")


def test_overlay_registry_with_explicit_defs():
    # A consumer rebuilds core ∪ exactly the bundle's verbs.
    reg = overlay_registry(verb_defs_for(["spiritolo/blend"]))
    assert reg.has("spiritolo/blend")
    assert not reg.has("spiritolo/top")   # not in this bundle
    assert reg.has("add")                 # core still present


def test_rejects_unknown_namespaced_verb_via_validator():
    # A registered namespace is not a blanket accept — unknown spiritolo verbs
    # still fail. (Guards against typos in emitted step verbs.)
    reg = overlay_registry([])
    doc = {"recipe": {
        "schema": "recipegf/cocktail/v1",
        "id": "com.spiritolo/x:v1", "title": "X",
        "ingredients": [{"name": "gin", "quantity": {"amount": 2, "unit": "oz"}}],
        "equipment": ["glass"],
        "steps": [{"verb": "spiritolo/nonexistent", "input": "gin", "using": "glass", "result": "r"}],
    }}
    assert not RecipeValidator(reg).validate(doc).valid


def test_core_registry_alone_lacks_spiritolo():
    # Baseline: without the overlay, spiritolo verbs are unknown.
    assert not VerbRegistry().has("spiritolo/blend")
