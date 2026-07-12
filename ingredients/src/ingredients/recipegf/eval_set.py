"""Eval set for the RecipeGF export converter.

Real cocktails modeled as :class:`SourceRecipe` fixtures (JSON-LD instructions +
parsed/roled ingredients, exactly the shape ``db.build_source_recipe`` assembles
from Supabase). The converter is pure, so — unlike the map/dedup evals — this
runs with **no DB**: ``recipegf-export --review`` exercises it directly.

Two kinds of case:
  - should-export: converts to an ``Ok`` whose bundle validates under
    ``core ∪ spiritolo/`` and satisfies the seam guarantees (reverse-DNS id,
    ``meta.slug == parse_recipe_id(id).slug``, meta triple). Add one whenever a
    new template/technique is taught.
  - should-abstain: converts to an ``Uncertain`` with a specific reason. Add one
    whenever an over-conversion is found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recipegf import parse_recipe_id

from .bundle import build_bundle, validate_bundle
from .converter import (
    Ok,
    SourceIngredient,
    SourceRecipe,
    Uncertain,
    convert_recipe,
)
from .verbs import verb_defs_for

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"


def _ing(pos, raw, name, slug, amount, unit, role, amount_max=None):
    return SourceIngredient(
        position=pos, raw_text=raw, name=name, slug=slug,
        amount=amount, amount_max=amount_max, unit=unit, role=role,
    )


def _recipe(name, url, instructions, ingredients):
    return SourceRecipe(
        canonical_name=name, source_url=url,
        jsonld={"recipeInstructions": instructions}, ingredients=ingredients,
    )


@dataclass(frozen=True)
class EvalCase:
    source: SourceRecipe
    # Exactly one expectation is set.
    expect_slug: str | None = None
    expect_spiritolo_verbs: list[str] = field(default_factory=list)
    expect_uncertain_reason: str | None = None


# ---- should-export ---------------------------------------------------------

_OLD_FASHIONED = _recipe(
    "Old Fashioned", "https://example.com/old-fashioned",
    [
        "Add the bourbon, simple syrup and bitters to a mixing glass with ice.",
        "Stir until well chilled, then strain over a large ice cube in a rocks glass.",
        "Express an orange twist over the drink and drop it in.",
    ],
    [
        _ing(1, "2 oz bourbon", "bourbon", "bourbon", 2, "oz", "base_spirit"),
        _ing(2, "0.25 oz simple syrup", "simple syrup", "simple-syrup", 0.25, "oz", "sweetener"),
        _ing(3, "2 dashes Angostura bitters", "angostura bitters", "angostura-bitters", 2, "dash", "bitters"),
        _ing(4, "1 large ice cube", "ice", "ice", 1, "cube", "ice"),
        _ing(5, "orange twist, for garnish", "orange twist", "orange", None, None, "garnish"),
    ],
)

_NEGRONI = _recipe(
    "Negroni", "https://example.com/negroni",
    "Add gin, Campari and sweet vermouth to a mixing glass with ice. Stir, then "
    "strain over fresh ice in a rocks glass. Garnish with an orange slice.",
    [
        _ing(1, "1 oz gin", "gin", "london-dry-gin", 1, "oz", "base_spirit"),
        _ing(2, "1 oz Campari", "campari", "campari", 1, "oz", "modifier"),
        _ing(3, "1 oz sweet vermouth", "sweet vermouth", "sweet-vermouth", 1, "oz", "modifier"),
        _ing(4, "1 orange slice", "orange slice", "orange", 1, "slice", "garnish"),
    ],
)

_MARGARITA = _recipe(
    "Margarita", "https://example.com/margarita",
    "Add the tequila, lime juice and triple sec to a shaker with ice. Shake "
    "until chilled and strain into a coupe. Garnish with a lime wheel.",
    [
        _ing(1, "2 oz blanco tequila", "tequila", "tequila-blanco", 2, "oz", "base_spirit"),
        _ing(2, "1 oz lime juice", "lime juice", "lime-juice", 1, "oz", "citrus"),
        _ing(3, "0.75 oz triple sec", "triple sec", "triple-sec", 0.75, "oz", "modifier"),
        _ing(4, "1 lime wheel", "lime wheel", "lime", 1, "wheel", "garnish"),
    ],
)

_DAIQUIRI = _recipe(
    "Daiquiri", "https://example.com/daiquiri",
    "Shake the rum, lime juice and simple syrup with ice, then strain into a "
    "chilled coupe.",
    [
        _ing(1, "2 oz white rum", "white rum", "white-rum", 2, "oz", "base_spirit"),
        _ing(2, "1 oz lime juice", "lime juice", "lime-juice", 1, "oz", "citrus"),
        _ing(3, "0.75 oz simple syrup", "simple syrup", "simple-syrup", 0.75, "oz", "sweetener"),
    ],
)

_FROZEN_DAIQUIRI = _recipe(
    "Frozen Daiquiri", "https://example.com/frozen-daiquiri",
    "Combine the rum, lime juice, simple syrup and ice in a blender. Blend "
    "until smooth and pour into a chilled glass.",
    [
        _ing(1, "2 oz white rum", "white rum", "white-rum", 2, "oz", "base_spirit"),
        _ing(2, "1 oz lime juice", "lime juice", "lime-juice", 1, "oz", "citrus"),
        _ing(3, "0.5 oz simple syrup", "simple syrup", "simple-syrup", 0.5, "oz", "sweetener"),
        _ing(4, "1 cup ice", "ice", "ice", 1, "cup", "ice"),
    ],
)

_GIN_AND_TONIC = _recipe(
    "Gin and Tonic", "https://example.com/gin-and-tonic",
    "Fill a highball glass with ice. Add the gin, then top with tonic water. "
    "Garnish with a lime wedge.",
    [
        _ing(1, "2 oz gin", "gin", "london-dry-gin", 2, "oz", "base_spirit"),
        _ing(2, "4 oz tonic water", "tonic water", "tonic-water", 4, "oz", "dilution"),
        _ing(3, "1 lime wedge", "lime wedge", "lime", 1, "wedge", "garnish"),
        _ing(4, "ice", "ice", "ice", None, None, "ice"),
    ],
)

# ---- should-abstain --------------------------------------------------------

# D6 governance: an ingredient the mapper couldn't resolve to a *registered*
# taxonomy slug (slug=None) does NOT fall back to a kebab-slug of the parsed
# name — that would emit an ungoverned token. It abstains → propose→review.
_UNRESOLVED_INGREDIENT = _recipe(
    "Whiskey Highball", "https://example.com/whiskey-highball",
    "Build over ice in a highball glass: add the whiskey, then top with soda "
    "water.",
    [
        _ing(1, "2 oz Japanese whisky", "japanese whisky", None, 2, "oz", "base_spirit"),
        _ing(2, "4 oz soda water", "soda water", None, 4, "oz", "dilution"),
        _ing(3, "ice", "ice", None, None, None, "ice"),
    ],
)

_MOJITO = _recipe(
    "Mojito", "https://example.com/mojito",
    "Muddle the mint and sugar in a glass. Add the rum and lime juice, fill "
    "with crushed ice and top with soda.",
    [
        _ing(1, "2 oz white rum", "white rum", "white-rum", 2, "oz", "base_spirit"),
        _ing(2, "1 oz lime juice", "lime juice", "lime-juice", 1, "oz", "citrus"),
    ],
)

_NO_TECHNIQUE = _recipe(
    "Mystery Punch", "https://example.com/mystery",
    "A delightful crowd-pleaser for any occasion.",
    [
        _ing(1, "2 oz rum", "rum", "white-rum", 2, "oz", "base_spirit"),
    ],
)

_UNTRANSLATABLE_UNIT = _recipe(
    "Two-Part Sour", "https://example.com/two-part-sour",
    "Stir the two parts together with ice and strain.",
    [
        # "part" is a relative unit with no absolute RecipeGF equivalent.
        _ing(1, "2 parts whiskey", "whiskey", "bourbon", 2, "part", "base_spirit"),
        _ing(2, "1 part lemon juice", "lemon juice", "lemon-juice", 1, "part", "citrus"),
    ],
)


CASES: list[EvalCase] = [
    EvalCase(_OLD_FASHIONED, expect_slug="old-fashioned"),
    EvalCase(_NEGRONI, expect_slug="negroni"),
    EvalCase(_MARGARITA, expect_slug="margarita"),
    EvalCase(_DAIQUIRI, expect_slug="daiquiri"),
    EvalCase(_FROZEN_DAIQUIRI, expect_slug="frozen-daiquiri",
             expect_spiritolo_verbs=["spiritolo/blend"]),
    EvalCase(_GIN_AND_TONIC, expect_slug="gin-and-tonic",
             expect_spiritolo_verbs=["spiritolo/top"]),
    EvalCase(_UNRESOLVED_INGREDIENT, expect_uncertain_reason="unresolved_ingredient"),
    EvalCase(_MOJITO, expect_uncertain_reason="muddle_unsupported"),
    EvalCase(_NO_TECHNIQUE, expect_uncertain_reason="no_technique"),
    EvalCase(_UNTRANSLATABLE_UNIT, expect_uncertain_reason="unknown_unit"),
]


def evaluate_case(case: EvalCase) -> tuple[bool, str]:
    """Return (ok, detail) for one case."""
    result = convert_recipe(case.source)

    if case.expect_uncertain_reason is not None:
        if not isinstance(result, Uncertain):
            return False, f"expected Uncertain({case.expect_uncertain_reason}), got Ok"
        if result.reason != case.expect_uncertain_reason:
            return False, f"expected reason {case.expect_uncertain_reason!r}, got {result.reason!r} ({result.detail})"
        return True, result.reason

    # should-export
    if not isinstance(result, Ok):
        return False, f"expected Ok, got Uncertain({result.reason}: {result.detail})"
    if result.slug != case.expect_slug:
        return False, f"expected slug {case.expect_slug!r}, got {result.slug!r}"
    if result.spiritolo_verbs != case.expect_spiritolo_verbs:
        return False, f"expected verbs {case.expect_spiritolo_verbs}, got {result.spiritolo_verbs}"

    bundle = build_bundle(
        result.recipe, verb_defs_for(result.spiritolo_verbs),
        slug=result.slug, source=case.source.source_url, imported_at=_IMPORTED_AT,
    )
    vr = validate_bundle(bundle)
    if not vr.valid:
        return False, "; ".join(f"{e.path}: {e.message}" for e in vr.errors[:3])

    # Seam guarantees.
    parsed = parse_recipe_id(bundle["recipe"]["id"])
    if parsed.authority != "com.spiritolo":
        return False, f"authority {parsed.authority!r} not reverse-DNS com.spiritolo"
    if parsed.slug != bundle["meta"]["slug"]:
        return False, f"meta.slug {bundle['meta']['slug']!r} != id slug {parsed.slug!r}"
    if set(bundle["meta"]) != {"slug", "source", "imported_at"}:
        return False, f"meta keys {sorted(bundle['meta'])} != slug/source/imported_at"
    return True, f"{result.slug} ({len(bundle['recipe']['steps'])} steps)"


def run_eval() -> dict[str, Any]:
    """Run every case. Returns ``{passed, failed, cases:[{name, ok, detail}]}``."""
    cases_out: list[dict[str, Any]] = []
    passed = failed = 0
    for case in CASES:
        ok, detail = evaluate_case(case)
        cases_out.append({"name": case.source.canonical_name, "ok": ok, "detail": detail})
        if ok:
            passed += 1
        else:
            failed += 1
    return {"passed": passed, "failed": failed, "cases": cases_out}
