"""End-to-end converter behavior + seam guarantees. Pure-Python (no DB).

Done-criteria coverage: a handful of real recipes emit bundles that validate
under core ∪ spiritolo/ and carry reverse-DNS ids + the meta triple.
"""

from __future__ import annotations

import pytest
from recipegf import (
    RecipeValidator,
    VerbRegistry,
    is_valid_recipe_id,
    parse_recipe_id,
)

from ingredients.recipegf import convert_recipe
from ingredients.recipegf.bundle import build_bundle, validate_bundle
from ingredients.recipegf.converter import (
    Ok,
    SourceIngredient,
    SourceRecipe,
    Uncertain,
)
from ingredients.recipegf.eval_set import CASES, run_eval
from ingredients.recipegf.verbs import verb_defs_for

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"


def _bundle_for(source: SourceRecipe):
    res = convert_recipe(source)
    assert isinstance(res, Ok), res
    return res, build_bundle(
        res.recipe, verb_defs_for(res.spiritolo_verbs),
        slug=res.slug, source=source.source_url, imported_at=_IMPORTED_AT,
    )


# ---- the eval set is the real-recipe corpus --------------------------------


def test_eval_set_all_pass():
    report = run_eval()
    failures = [c for c in report["cases"] if not c["ok"]]
    assert not failures, failures
    assert report["passed"] == len(CASES)


@pytest.mark.parametrize("case", [c for c in CASES if c.expect_slug], ids=lambda c: c.expect_slug)
def test_each_exported_bundle_validates_under_core_union_spiritolo(case):
    res, bundle = _bundle_for(case.source)
    # Validate exactly as Barbot (P3) would: core ∪ bundle["verbs"], nothing else.
    registry = VerbRegistry().load_overlay(bundle["verbs"])
    result = RecipeValidator(registry).validate({"recipe": bundle["recipe"]})
    assert result.valid, [(e.path, e.message) for e in result.errors]


@pytest.mark.parametrize("case", [c for c in CASES if c.expect_slug], ids=lambda c: c.expect_slug)
def test_seam_reverse_dns_id_and_slug_equality(case):
    _res, bundle = _bundle_for(case.source)
    recipe_id = bundle["recipe"]["id"]
    assert is_valid_recipe_id(recipe_id)
    parsed = parse_recipe_id(recipe_id)                       # RecipeGF parser, not string splitting
    assert parsed.authority == "com.spiritolo"               # reverse-DNS authority
    assert parsed.slug == bundle["meta"]["slug"] == case.expect_slug
    assert parsed.version == 1


@pytest.mark.parametrize("case", [c for c in CASES if c.expect_slug], ids=lambda c: c.expect_slug)
def test_meta_triple_present(case):
    _res, bundle = _bundle_for(case.source)
    assert set(bundle["meta"]) == {"slug", "source", "imported_at"}
    assert bundle["meta"]["source"] == case.source.source_url
    assert bundle["meta"]["imported_at"] == _IMPORTED_AT


def test_bundle_verbs_are_only_the_ones_used():
    # Frozen Daiquiri uses exactly spiritolo/blend; the bundle carries only it.
    fd = next(c for c in CASES if c.expect_slug == "frozen-daiquiri")
    res, bundle = _bundle_for(fd.source)
    assert res.spiritolo_verbs == ["spiritolo/blend"]
    assert [d["verb"] for d in bundle["verbs"]] == ["spiritolo/blend"]

    # A purely-core recipe carries an empty verbs list.
    of = next(c for c in CASES if c.expect_slug == "old-fashioned")
    _res2, bundle2 = _bundle_for(of.source)
    assert bundle2["verbs"] == []


def test_bundle_is_self_contained_no_registry_lookup():
    # Rebuild from ONLY the bundle contents (no in-repo overlay), as a fresh
    # consumer would — it must still validate.
    fd = next(c for c in CASES if c.expect_slug == "frozen-daiquiri")
    _res, bundle = _bundle_for(fd.source)
    result = validate_bundle(bundle)
    assert result.valid


# ---- abstain corpus --------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.expect_uncertain_reason],
    ids=lambda c: c.expect_uncertain_reason,
)
def test_abstain_cases(case):
    res = convert_recipe(case.source)
    assert isinstance(res, Uncertain)
    assert res.reason == case.expect_uncertain_reason


# ---- specific edge cases ---------------------------------------------------


def _src(name, instr, ings):
    return SourceRecipe(canonical_name=name, source_url="https://ex/x",
                        jsonld={"recipeInstructions": instr}, ingredients=ings)


def test_unresolvable_ingredient_name_is_uncertain():
    src = _src("Nameless", "Stir and strain.", [
        SourceIngredient(position=1, raw_text="???", name=None, slug=None,
                         amount=2, unit="oz", role="base_spirit"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Uncertain) and res.reason == "unresolved_ingredient"


def test_duplicate_ingredient_slug_is_uncertain():
    src = _src("Doubled", "Stir and strain.", [
        SourceIngredient(position=1, raw_text="1 oz gin", name="gin", slug="gin",
                         amount=1, unit="oz", role="base_spirit"),
        SourceIngredient(position=2, raw_text="1 oz gin", name="gin", slug="gin",
                         amount=1, unit="oz", role="base_spirit"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Uncertain) and res.reason == "duplicate_ingredient"


def test_no_body_ingredients_is_uncertain():
    src = _src("Garnish Only", "Stir and strain.", [
        SourceIngredient(position=1, raw_text="orange twist", name="orange twist",
                         slug="orange", amount=None, unit=None, role="garnish"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Uncertain) and res.reason == "no_body"


def test_missing_amount_on_body_is_uncertain():
    src = _src("Amountless", "Stir and strain.", [
        SourceIngredient(position=1, raw_text="gin", name="gin", slug="gin",
                         amount=None, unit="oz", role="base_spirit"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Uncertain) and res.reason == "missing_amount"


def test_bitters_without_amount_defaults_to_one():
    # A dash-less bitters accent defaults to amount 1 rather than abstaining.
    src = _src("Dashy", "Stir the gin with bitters and strain.", [
        SourceIngredient(position=1, raw_text="2 oz gin", name="gin", slug="gin",
                         amount=2, unit="oz", role="base_spirit"),
        SourceIngredient(position=2, raw_text="a dash of bitters", name="bitters",
                         slug="angostura-bitters", amount=None, unit="dash", role="bitters"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Ok)
    amounts = {i["name"]: i["quantity"]["amount"] for i in res.recipe["ingredients"]}
    assert amounts["angostura-bitters"] == 1.0


def test_bare_spiritolo_recipe_id_is_rejected_by_grammar():
    # Seam guarantee: spiritolo is a VERB namespace, never a recipe authority.
    assert not is_valid_recipe_id("spiritolo/old-fashioned:v1")
    # ...while our reverse-DNS authority is accepted.
    assert is_valid_recipe_id("com.spiritolo/old-fashioned:v1")


def test_tbsp_unit_translated_to_recipegf_valid():
    src = _src("Spoonful", "Stir the whiskey and syrup with ice and strain.", [
        SourceIngredient(position=1, raw_text="2 oz whiskey", name="whiskey",
                         slug="bourbon", amount=2, unit="oz", role="base_spirit"),
        SourceIngredient(position=2, raw_text="1 tbsp rich syrup", name="rich syrup",
                         slug="rich-syrup", amount=1, unit="tbsp", role="sweetener"),
    ])
    res = convert_recipe(src)
    assert isinstance(res, Ok)
    units = {i["name"]: i["quantity"]["unit"] for i in res.recipe["ingredients"]}
    assert units["rich-syrup"] == "Tbs"
