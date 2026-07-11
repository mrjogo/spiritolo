"""JSON-LD + parsed-ingredients → a RecipeGF verb-frame ``recipe`` (D2).

The converter is deterministic and pure (no DB, no network): it takes a
:class:`SourceRecipe` — a cluster's canonical name plus its representative
recipe's JSON-LD and parsed+roled ``recipe_ingredients`` — and returns either

  - :class:`Ok` — a validated RecipeGF ``recipe`` object + the ``spiritolo/``
    verbs it uses, or
  - :class:`Uncertain` — a machine-readable reason routed to propose→review.

It never emits a plausible-but-wrong doc: any ambiguity (no technique, an
unresolved ingredient, an untranslatable unit, a muddle it can't place, a
duplicate ingredient, an empty body, or a doc that fails RecipeValidator)
becomes an ``Uncertain`` outcome. Every ``Ok`` recipe is validated against
``core ∪ spiritolo/`` before it is returned, so the export seam guarantee
("each bundle validates") holds by construction.

Follows Spiritolo's versioned-stage pattern: rules here are part of the
``CONVERTER_VERSION`` contract (see ``version.py``). An LLM Phase 2 that drains
the ``Uncertain`` queue would slot in behind the same seam — this deterministic
pass is Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recipegf import RecipeId, format_recipe_id, is_valid_recipe_id

from .slug import mint_slug, slugify
from .technique import (
    TOPPER_HINTS,
    Technique,
    flatten_instructions,
    infer_technique,
    mentions_muddle,
)
from .verbs import overlay_registry, verb_defs_for
from .version import RECIPE_AUTHORITY, RECIPE_ENCODING_VERSION, RECIPE_SCHEMA

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceIngredient:
    """One parsed ``recipe_ingredients`` row, joined to its taxonomy slug."""

    raw_text: str
    position: int
    name: str | None = None          # parsed ingredient name (recipe_ingredients.name)
    slug: str | None = None          # taxonomy_nodes.slug, if the mapper resolved it
    amount: float | None = None
    amount_max: float | None = None
    unit: str | None = None
    role: str | None = None          # dedup role: base_spirit/citrus/ice/garnish/...


@dataclass(frozen=True)
class SourceRecipe:
    """A drink to convert: cluster identity + representative recipe content."""

    canonical_name: str
    source_url: str
    jsonld: dict[str, Any]
    ingredients: list[SourceIngredient]


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ok:
    """A successful conversion: a validated recipe + the extension verbs used."""

    slug: str
    recipe: dict[str, Any]
    spiritolo_verbs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Uncertain:
    """A conversion that needs review. ``reason`` is a stable machine code;
    ``detail`` is a human-readable specifics string."""

    reason: str
    detail: str


ConversionResult = Ok | Uncertain


# Stable reason codes (also documented in docs/recipegf-export.md).
REASON_NO_SLUG = "no_slug"
REASON_NO_TECHNIQUE = "no_technique"
REASON_MUDDLE_UNSUPPORTED = "muddle_unsupported"
REASON_UNRESOLVED_INGREDIENT = "unresolved_ingredient"
REASON_UNKNOWN_UNIT = "unknown_unit"
REASON_MISSING_AMOUNT = "missing_amount"
REASON_DUPLICATE_INGREDIENT = "duplicate_ingredient"
REASON_NO_BODY = "no_body"
REASON_VALIDATION_FAILED = "validation_failed"


# ---------------------------------------------------------------------------
# Unit + ingredient normalization
# ---------------------------------------------------------------------------

# Parser-canonical units that RecipeGF's UnitValidator rejects but that map
# cleanly onto a RecipeGF-valid unit. Everything the validator already accepts
# passes through untouched; anything neither accepted nor here → uncertain.
_UNIT_TRANSLATE = {"tbsp": "Tbs", "pint": "pnt", "quart": "qt", "gallon": "gal"}

# Count units where a missing amount defaults to 1 (a single piece).
_COUNT_UNITS = {"each", "cube", "piece", "slice", "wedge", "wheel", "sprig", "twist"}

# Roles whose missing amount we default to 1 (a garnish/dash accent).
_DEFAULT_ONE_ROLES = {"garnish", "bitters"}

# Name/raw tokens that mark a garnish when dedup roles are absent.
_GARNISH_HINTS = (
    "twist", "peel", "zest", "wheel", "wedge", "slice", "cherry", "mint",
    "olive", "sprig", "garnish", "rind", "leaf",
)

_ICE_NAMES = {"ice", "crushed-ice", "cracked-ice", "ice-cube", "ice-cubes"}


def _recipegf_unit(unit: str | None) -> str | None:
    """Translate a parser unit to a RecipeGF-valid unit, or ``None`` if it has
    no faithful RecipeGF equivalent (relative units like ``part``, exotic
    count nouns like ``leaf``)."""
    from recipegf import UnitValidator

    if not unit:
        return None
    if UnitValidator().is_valid(unit):
        return unit
    return _UNIT_TRANSLATE.get(unit)


def _ingredient_name(ing: SourceIngredient) -> str | None:
    """The RecipeGF ingredient name for a row: the taxonomy slug when the
    mapper resolved one (the Barbot slug→object seam), else a kebab-slug of
    the parsed name. ``None`` when neither is usable."""
    if ing.slug:
        return ing.slug
    if ing.name:
        slug = slugify(ing.name)
        return slug or None
    return None


def _is_ice(ing: SourceIngredient, name: str) -> bool:
    return ing.role == "ice" or name in _ICE_NAMES


def _is_garnish(ing: SourceIngredient, name: str) -> bool:
    if ing.role == "garnish":
        return True
    if ing.role is not None:
        return False  # a non-garnish role is authoritative
    hay = f"{name} {ing.raw_text}".lower()
    return any(h in hay for h in _GARNISH_HINTS)


def _is_topper(name: str, ing: SourceIngredient) -> bool:
    hay = f"{name} {ing.raw_text}".lower()
    return any(h in hay for h in TOPPER_HINTS)


# ---------------------------------------------------------------------------
# Ingredient assembly
# ---------------------------------------------------------------------------


@dataclass
class _Prepared:
    """An ingredient resolved to a RecipeGF (name, quantity) + its bucket."""

    name: str
    quantity: dict[str, Any]
    bucket: str  # "body" | "ice" | "garnish"
    is_topper: bool


def _prepare_ingredients(
    ingredients: list[SourceIngredient],
) -> list[_Prepared] | Uncertain:
    """Resolve every source ingredient to a RecipeGF ingredient + bucket, or
    return the first :class:`Uncertain` blocker encountered."""
    prepared: list[_Prepared] = []
    seen_names: set[str] = set()

    for ing in ingredients:
        name = _ingredient_name(ing)
        if name is None:
            return Uncertain(
                REASON_UNRESOLVED_INGREDIENT,
                f"ingredient at position {ing.position} has no resolvable name "
                f"(raw={ing.raw_text!r})",
            )

        bucket = "body"
        if _is_ice(ing, name):
            bucket = "ice"
        elif _is_garnish(ing, name):
            bucket = "garnish"

        rgf_unit = _recipegf_unit(ing.unit)
        amount = ing.amount

        if rgf_unit is None:
            # No usable unit. Countable buckets default to a single "each".
            if bucket in ("ice", "garnish"):
                rgf_unit = "each"
                amount = amount if amount is not None else 1.0
            elif ing.unit:
                return Uncertain(
                    REASON_UNKNOWN_UNIT,
                    f"unit {ing.unit!r} on {name!r} has no RecipeGF equivalent",
                )
            else:
                return Uncertain(
                    REASON_MISSING_AMOUNT,
                    f"body ingredient {name!r} has no unit (raw={ing.raw_text!r})",
                )

        if amount is None:
            if rgf_unit in _COUNT_UNITS or ing.role in _DEFAULT_ONE_ROLES:
                amount = 1.0
            else:
                return Uncertain(
                    REASON_MISSING_AMOUNT,
                    f"ingredient {name!r} has unit {rgf_unit!r} but no amount",
                )

        if name in seen_names:
            return Uncertain(
                REASON_DUPLICATE_INGREDIENT,
                f"two ingredients resolve to the same name {name!r}",
            )
        seen_names.add(name)

        prepared.append(
            _Prepared(
                name=name,
                quantity={"amount": float(amount), "unit": rgf_unit},
                bucket=bucket,
                is_topper=bucket == "body" and _is_topper(name, ing),
            )
        )

    return prepared


# ---------------------------------------------------------------------------
# Step templates
# ---------------------------------------------------------------------------


def _garnish_steps(
    garnishes: list[_Prepared], start_result: str
) -> tuple[list[dict[str, Any]], str]:
    """Chain one ``garnish`` step per garnish onto ``start_result``. Returns
    (steps, final_result). No garnishes → ([], start_result)."""
    steps: list[dict[str, Any]] = []
    cur = start_result
    for i, g in enumerate(garnishes):
        result = "finished_drink" if i == len(garnishes) - 1 else f"garnished_{i}"
        steps.append({"verb": "garnish", "input": g.name, "to": cur, "result": result})
        cur = result
    return steps, cur


def _build_steps(
    technique: Technique, prepared: list[_Prepared]
) -> tuple[list[str], list[dict[str, Any]], set[str]] | Uncertain:
    """Produce (equipment, steps, spiritolo_verbs) for a technique, or an
    :class:`Uncertain` if the ingredient buckets can't fill the template."""
    body = [p for p in prepared if p.bucket == "body"]
    ice = [p for p in prepared if p.bucket == "ice"]
    garnishes = [p for p in prepared if p.bucket == "garnish"]
    ice_names = [p.name for p in ice]
    used: set[str] = set()

    if technique is Technique.STIR:
        if not body:
            return Uncertain(REASON_NO_BODY, "no body ingredients to stir")
        equipment = ["mixing_glass", "bar_spoon", "rocks_glass"]
        steps: list[dict[str, Any]] = [
            {"verb": "add", "input": [p.name for p in body], "to": "mixing_glass", "result": "combined"},
            {"verb": "stir", "input": "combined", "using": "bar_spoon", "result": "stirred"},
        ]
        if ice_names:
            steps.append({"verb": "add", "input": ice_names, "to": "rocks_glass", "result": "iced_glass"})
            strain_to = "iced_glass"
        else:
            strain_to = "rocks_glass"
        steps.append({"verb": "strain", "input": "stirred", "to": strain_to, "using": "bar_spoon", "result": "poured"})
        gsteps, _ = _garnish_steps(garnishes, "poured")
        steps.extend(gsteps)
        return equipment, steps, used

    if technique is Technique.SHAKE:
        if not body:
            return Uncertain(REASON_NO_BODY, "no body ingredients to shake")
        equipment = ["shaker", "strainer", "coupe_glass"]
        combined_input = [p.name for p in body] + ice_names
        steps = [
            {"verb": "add", "input": combined_input, "to": "shaker", "result": "combined"},
            {"verb": "shake", "input": "combined", "result": "shaken"},
            {"verb": "strain", "input": "shaken", "to": "coupe_glass", "using": "strainer", "result": "poured"},
        ]
        gsteps, _ = _garnish_steps(garnishes, "poured")
        steps.extend(gsteps)
        return equipment, steps, used

    if technique is Technique.BLEND:
        if not body:
            return Uncertain(REASON_NO_BODY, "no body ingredients to blend")
        equipment = ["blender"]
        steps = [
            {"verb": "add", "input": [p.name for p in body] + ice_names, "to": "blender", "result": "blend_base"},
            {"verb": "spiritolo/blend", "input": "blend_base", "using": "blender", "result": "blended"},
        ]
        used.add("spiritolo/blend")
        gsteps, _ = _garnish_steps(garnishes, "blended")
        steps.extend(gsteps)
        return equipment, steps, used

    if technique is Technique.BUILD:
        base_body = [p for p in body if not p.is_topper]
        toppers = [p for p in body if p.is_topper]
        if not base_body and not toppers:
            return Uncertain(REASON_NO_BODY, "no body ingredients to build")
        equipment = ["highball_glass"]
        steps = []
        if ice_names:
            steps.append({"verb": "add", "input": ice_names, "to": "highball_glass", "result": "iced_glass"})
            cur = "iced_glass"
        else:
            cur = "highball_glass"
        if base_body:
            steps.append({"verb": "add", "input": [p.name for p in base_body], "to": cur, "result": "built"})
            cur = "built"
        for i, t in enumerate(toppers):
            result = f"topped_{i}"
            steps.append({"verb": "spiritolo/top", "input": t.name, "to": cur, "result": result})
            used.add("spiritolo/top")
            cur = result
        gsteps, _ = _garnish_steps(garnishes, cur)
        steps.extend(gsteps)
        return equipment, steps, used

    return Uncertain(REASON_NO_TECHNIQUE, f"unhandled technique {technique!r}")


# ---------------------------------------------------------------------------
# Top-level conversion
# ---------------------------------------------------------------------------


def convert_recipe(source: SourceRecipe) -> ConversionResult:
    """Convert one drink to a validated RecipeGF ``recipe`` object, or return
    an :class:`Uncertain` outcome for propose→review."""
    slug = mint_slug(source.canonical_name)
    if slug is None:
        return Uncertain(REASON_NO_SLUG, f"canonical_name {source.canonical_name!r} yields no valid slug")

    text = flatten_instructions(source.jsonld)
    if mentions_muddle(text):
        return Uncertain(
            REASON_MUDDLE_UNSUPPORTED,
            "instructions mention muddling; v1 templates can't place a muddle step",
        )

    technique = infer_technique(source.jsonld)
    if technique is None:
        return Uncertain(REASON_NO_TECHNIQUE, "no stir/shake/build/blend keyword in instructions")

    prepared = _prepare_ingredients(source.ingredients)
    if isinstance(prepared, Uncertain):
        return prepared

    built = _build_steps(technique, prepared)
    if isinstance(built, Uncertain):
        return built
    equipment, steps, spiritolo_verbs = built

    recipe_id = format_recipe_id(RecipeId(RECIPE_AUTHORITY, slug, RECIPE_ENCODING_VERSION))
    # Defensive: the id must satisfy RecipeGF's grammar (a bare spiritolo/<slug>
    # would be rejected — spiritolo is a verb namespace, not a recipe authority).
    if not is_valid_recipe_id(recipe_id):
        return Uncertain(REASON_NO_SLUG, f"minted id {recipe_id!r} is not a valid recipe id")

    recipe = {
        "schema": RECIPE_SCHEMA,
        "id": recipe_id,
        "title": source.canonical_name,
        "ingredients": [{"name": p.name, "quantity": p.quantity} for p in prepared],
        "equipment": equipment,
        "steps": steps,
    }

    # Every Ok recipe validates under core ∪ spiritolo/ — the seam guarantee,
    # enforced here so an invalid doc can never leave as an Ok.
    used = sorted(spiritolo_verbs)
    registry = overlay_registry(verb_defs_for(used))
    from recipegf import RecipeValidator

    result = RecipeValidator(registry).validate({"recipe": recipe})
    if not result.valid:
        detail = "; ".join(f"{e.path}: {e.message}" for e in result.errors[:5])
        return Uncertain(REASON_VALIDATION_FAILED, detail)

    return Ok(slug=slug, recipe=recipe, spiritolo_verbs=used)
