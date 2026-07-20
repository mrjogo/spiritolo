# RecipeGF export

Spiritolo emits **validated RecipeGF pin-2 bundles** from its recipe data, so a
consumer (Barbot) can import finished, self-contained recipe docs with no
runtime cross-dependency on Spiritolo.

Depends on **RecipeGF v0.4.0** — the id grammar, `RecipeValidator`, the
`VerbRegistry` overlay API, and the namespace registry (the `spiritolo`
namespace is registered upstream). Pinned in
[`ingredients/pyproject.toml`](../ingredients/pyproject.toml) as a git tag dep.

## What it produces — the pin-2 bundle

One bundle per **recipe**. Shape:

```jsonc
{
  "recipe": { "schema": "recipegf/cocktail/v1", "id": "com.spiritolo/<slug>:v1",
              "title": ..., "ingredients": [...], "equipment": [...], "steps": [...] },
  "verbs":  [ <spiritolo/ verb-defs the recipe uses> ],   // self-contained
  "meta":   { "slug": "<slug>", "source": "<source_url>", "imported_at": "<ISO-8601>" }
}
```

**Seam guarantees** (enforced at generation; a violating bundle is never
emitted):

- The id is reverse-DNS `com.spiritolo/<slug>:v1` and passes
  `is_valid_recipe_id`. A bare `spiritolo/<slug>` id is **rejected** — the
  `spiritolo` namespace is for VERBS, not recipe authorities.
- Each ingredient carries a reverse-DNS `ref` (`com.spiritolo/<slug>`) minted
  from the shared taxonomy resolution — a portable identity, never a
  client-side slugified name.
- `meta.slug == parse_recipe_id(id).slug` (via RecipeGF's `parse_recipe_id`, not
  ad-hoc string splitting).
- The bundle is **self-contained**: it carries every `spiritolo/` verb-def its
  steps reference, so a consumer validates with zero external lookups —
  `RecipeValidator(VerbRegistry().load_overlay(bundle["verbs"])).validate({"recipe": bundle["recipe"]})`.
- `meta` carries the full `slug` / `source` / `imported_at` triple a consumer's
  import needs.

## Pipeline shape — convert-steps, then export-recipegf

The verb-frame projection is produced by two deterministic pipeline stages, both
versioned at `CONVERTER_VERSION` and run over the shared `stage_runs` work queue:

1. **`convert-steps`** — the pure technique→template converter
   ([`converter.py`](../ingredients/src/ingredients/recipegf/converter.py)) turns
   each mapped recipe (its `recipe_ingredients` joined to the shared
   `ingredient_resolutions`, plus the JSON-LD instructions) into RecipeGF
   verb-frame steps, written to `recipe_steps`, along with the derived
   `equipment` list and a kebab **slug** minted onto `recipes.recipe_slug`.
   Technique (`stir | shake | build | blend`) is inferred from the instruction
   text to select the step template; ingredient roles (to bucket
   ice/garnish/body) are classified inline from the taxonomy default role —
   ephemeral, not stored. A recipe the converter can't yet emit writes no steps
   and records a non-terminal `stage_runs` outcome: `pending` (an ingredient
   isn't resolved yet — it returns after the `map-ingredient` stage) or `proposes_new`
   (needs a rules/technique review, e.g. a muddle the templates can't place).

2. **`export-recipegf`** —
   [`generate.py`](../ingredients/src/ingredients/recipegf/generate.py)'s
   `generate_bundle` assembles the pin-2 bundle from the current rows + shared
   resolution + in-repo verb-defs and validates it against `core ∪ spiritolo/`;
   the stage then **freezes** that snapshot into `recipe_exports`. The
   `stage_runs` outcome is `resolved` (frozen), `pending` (an ingredient still
   isn't resolved), or `failed` (a seam violation — e.g. an unbuildable recipe).

Ingredient identity is governed: there is **no** slugify-the-parsed-name
fallback — an ingredient token is an identity, so it must be a slug registered
in Spiritolo's taxonomy (the shared `ingredient_resolutions`), never
client-side slugified (which can collide or emit an ungoverned token). Verbs are
exempt (closed RecipeGF vocab).

## Unit coverage

Unit vocabulary is delegated to RecipeGF's registries: the parser emits
RecipeGF-canonical unit names (`units.py` reads RecipeGF's `bar-units` and
`count-units` registries directly), and the converter validates with
`UnitValidator`, keeping no parallel unit table of its own. Its only local shim
is a 4-entry spelling bridge (`tbsp→Tbs`, `pint→pnt`, `quart→qt`, `gallon→gal`)
for surfaces RecipeGF doesn't alias. A unit with no faithful RecipeGF
equivalent routes to review (`unknown_unit`) rather than being silently
coerced.

## `spiritolo/` extension verbs

Beyond RecipeGF core (`add`, `stir`, `shake`, `strain`, `muddle`, `rim`,
`garnish`, `express`), Spiritolo defines extension verbs as self-describing YAML
under
[`recipegf/verbs/`](../ingredients/src/ingredients/recipegf/verbs), loaded via
the overlay API (verbs iterate in-repo — no RecipeGF PR per verb):

- `spiritolo/blend` — blend in place until smooth (frozen drinks).
- `spiritolo/top` — top a built drink with an (effervescent) ingredient, added
  last without mixing.

A bundle embeds only the defs its recipe actually uses.

## Storage — relational, generated on demand

The verb-frame recipe is **not stored as a bundle blob**. It lives in the shared
relational content model
([`20260720120000_content_relational_model.sql`](../supabase/migrations/20260720120000_content_relational_model.sql)):

- `recipes` — one header row per recipe: the RecipeGF-shaped fields (`title`,
  `equipment text[]`, the minted `recipe_slug`) alongside the raw source
  JSON-LD (`source`) and `source_url`.
- `recipe_ingredients` — the RecipeGF ingredient rows (parse output): `position`,
  `name`, `amount`, `unit`, `modifiers`.
- `recipe_steps` — the verb-frame steps (convert output): `step_index`, `verb`,
  `result`, `roles` (jsonb — the per-verb role map is genuinely schemaless),
  `modifiers` (text[]).
- `ingredient_resolutions` — the **shared**, name-keyed ingredient→taxonomy
  resolution. Each ingredient's portable `ref` is minted from here, so a
  taxonomy correction touches one shared row and every bundle that uses that
  ingredient follows on the next generation — no per-recipe rewrite.

**The pin-2 bundle is a projection, generated on demand** by `generate_bundle`
from those rows every time it's asked for, so the live representation stays
current with the taxonomy. A **published** bundle is frozen separately by the
`export-recipegf` stage into `recipe_exports` — one row per `(recipe_id,
converter_version)` carrying the frozen `bundle` jsonb, its `recipe_slug` /
`recipe_ref` (`com.spiritolo/<slug>:v1`), and `exported_at`. The export work
queue is "recipes with no `recipe_exports` row at the current
`CONVERTER_VERSION`" — a `NOT EXISTS`, like every stage's queue.

## Read surface

`recipe_exports` is the frozen, published surface, indexed by `recipe_slug`. It
carries RLS with an admin-only read policy (authenticated + `is_admin()`) and no
anon/public grant; the `/ops` console browses frozen exports and can regenerate
a live bundle on demand for any recipe. A consumer's import pulls a drink's
bundle by its **slug** — the Spiritolo-owned, stable join/sync key written to
`recipes.recipe_slug` and frozen into `recipe_exports.recipe_slug`.

## CLI

```bash
# Convert mapped recipes into verb-frame steps (writes recipe_steps + slug).
cd ingredients && uv run python -m ingredients.cli convert-steps

# Freeze the pin-2 bundle for every recipe lacking one at the current version.
cd ingredients && uv run python -m ingredients.cli export-recipegf

# Scope either stage to one site, capped.
cd ingredients && uv run python -m ingredients.cli export-recipegf --site punch --limit 50

# Run the whole pipeline in order ( … -> convert-steps -> cluster-recipes -> export-recipegf ).
cd ingredients && uv run python -m ingredients.cli cold-build
```

Every subcommand takes only `--site` / `--limit`. To re-run a stage, delete its
`stage_runs` rows or bump the version constant. Writes go to whatever
`SUPABASE_DB_URL` points at.

## Versioning

`CONVERTER_VERSION` in
[`recipegf/version.py`](../ingredients/src/ingredients/recipegf/version.py). Bump
when conversion output would change for the same input (technique keywords, step
templates, slug rules, unit handling, the spiritolo verb set, the id encoding
version), then re-run `convert-steps` + `export-recipegf`; recipes left at the old version
re-queue as their `stage_runs` rows fall behind the current version.

## Eval set

[`recipegf/eval_set.py`](../ingredients/src/ingredients/recipegf/eval_set.py) —
real cocktails (Old Fashioned, Negroni, Margarita, Daiquiri, Frozen Daiquiri,
Gin & Tonic, Whiskey Highball) as should-export cases, plus should-abstain cases
(Mojito → muddle, no-technique, untranslatable unit). The converter is pure, so
the eval set needs no DB — the test suite
([`ingredients/tests/`](../ingredients/tests)) exercises it. Add a should-export
case when you teach a new template/technique; add a should-abstain case when you
find an over-conversion.
