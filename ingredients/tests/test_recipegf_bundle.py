"""Bundle assembly seam guarantees. Pure-Python (no DB)."""

from __future__ import annotations

import pytest

from ingredients.recipegf.bundle import BundleError, build_bundle, validate_bundle

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"


def _recipe(recipe_id="com.spiritolo/negroni:v1"):
    return {
        "schema": "recipegf/cocktail/v1",
        "id": recipe_id,
        "title": "Negroni",
        "ingredients": [{"name": "gin", "quantity": {"amount": 1, "unit": "oz"}}],
        "equipment": ["mixing_glass", "bar_spoon", "rocks_glass"],
        "steps": [
            {"verb": "add", "input": ["gin"], "to": "mixing_glass", "result": "m"},
            {"verb": "stir", "input": "m", "using": "bar_spoon", "result": "s"},
            {"verb": "strain", "input": "s", "to": "rocks_glass", "using": "bar_spoon", "result": "p"},
        ],
    }


def test_build_bundle_happy_path():
    bundle = build_bundle(_recipe(), [], slug="negroni",
                          source="https://ex/n", imported_at=_IMPORTED_AT)
    assert bundle["recipe"]["id"] == "com.spiritolo/negroni:v1"
    assert bundle["meta"] == {"slug": "negroni", "source": "https://ex/n",
                              "imported_at": _IMPORTED_AT}
    assert validate_bundle(bundle).valid


def test_build_bundle_rejects_slug_id_mismatch():
    with pytest.raises(BundleError, match="!="):
        build_bundle(_recipe(), [], slug="martini",   # mismatches id's negroni
                     source="https://ex/n", imported_at=_IMPORTED_AT)


def test_build_bundle_rejects_non_reverse_dns_authority():
    # A bare spiritolo/<slug> id fails the grammar outright.
    with pytest.raises(BundleError, match="valid RecipeGF recipe id"):
        build_bundle(_recipe("spiritolo/negroni:v1"), [], slug="negroni",
                     source="https://ex/n", imported_at=_IMPORTED_AT)


def test_build_bundle_rejects_foreign_authority():
    with pytest.raises(BundleError, match="reverse-DNS"):
        build_bundle(_recipe("com.barbot/negroni:v1"), [], slug="negroni",
                     source="https://ex/n", imported_at=_IMPORTED_AT)


def test_build_bundle_rejects_invalid_recipe():
    bad = _recipe()
    bad["steps"].append({"verb": "nonexistent", "input": "p", "result": "z"})
    with pytest.raises(BundleError, match="failed validation"):
        build_bundle(bad, [], slug="negroni",
                     source="https://ex/n", imported_at=_IMPORTED_AT)


def test_validate_bundle_is_the_p3_consumer_check():
    # validate_bundle rebuilds core ∪ bundle["verbs"] and validates
    # {"recipe": ...} — the exact call P3 makes on import.
    bundle = build_bundle(_recipe(), [], slug="negroni",
                          source="https://ex/n", imported_at=_IMPORTED_AT)
    assert validate_bundle(bundle).valid
    # Corrupt the recipe post-hoc → the consumer check catches it.
    bundle["recipe"]["steps"][0]["verb"] = "bogus"
    assert not validate_bundle(bundle).valid
