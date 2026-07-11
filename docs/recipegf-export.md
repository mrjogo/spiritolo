# RecipeGF export (P2)

Spiritolo emits **validated RecipeGF pin-2 bundles** from its recipe data, so
Barbot (P3) can import finished, self-contained recipe docs with no runtime
cross-dependency on Spiritolo. This is the Spiritolo half of the cross-repo
recipe-identity design; the frozen interface pins live in Barbot's
`docs/architecture/recipe-cross-repo.md`.

Depends on **RecipeGF v0.3.0** (P1) — the id grammar, `RecipeValidator`, the
`VerbRegistry` overlay API, and the namespace registry (the `spiritolo`
namespace is already registered upstream). Pinned in
[`ingredients/pyproject.toml`](../ingredients/pyproject.toml) as a git tag dep.

## What it produces — the pin-2 bundle

One bundle per **drink** (a `recipe_clusters` row). Shape:

```jsonc
{
  "recipe": { "schema": "recipegf/cocktail/v1", "id": "com.spiritolo/<slug>:v1",
              "title": ..., "ingredients": [...], "equipment": [...], "steps": [...] },
  "verbs":  [ <spiritolo/ verb-defs the recipe uses> ],   // self-contained
  "meta":   { "slug": "<slug>", "source": "<source_url>", "imported_at": "<ISO-8601>" }
}
```

**Seam guarantees** (enforced at build time; a violating bundle is never
emitted):

- The id is reverse-DNS `com.spiritolo/<slug>:v1` and passes
  `is_valid_recipe_id`. A bare `spiritolo/<slug>` id is **rejected** — the
  `spiritolo` namespace is for VERBS, not recipe authorities.
- `meta.slug == parse_recipe_id(id).slug` (via RecipeGF's `parse_recipe_id`, not
  ad-hoc string splitting).
- The bundle is **self-contained**: it carries every `spiritolo/` verb-def its
  steps reference, so a consumer validates with zero external lookups —
  `RecipeValidator(VerbRegistry().load_overlay(bundle["verbs"])).validate({"recipe": bundle["recipe"]})`.
- `meta` carries the full `slug` / `source` / `imported_at` triple Barbot's
  import DB CHECK needs.

## Pipeline shape

Deterministic **Phase 1**, following Spiritolo's versioned-stage +
propose→review pattern:

1. **Slug** — [`slug.py`](../ingredients/src/ingredients/recipegf/slug.py) mints a
   kebab-case slug from `recipe_clusters.canonical_name` (owned by Spiritolo, the
   drink registry). No valid slug → review.
2. **Technique** —
   [`technique.py`](../ingredients/src/ingredients/recipegf/technique.py) infers
   `stir | shake | build | blend` from the JSON-LD `recipeInstructions` text. No
   keyword, or a muddle it can't place → review.
3. **Convert** —
   [`converter.py`](../ingredients/src/ingredients/recipegf/converter.py) turns the
   cluster's representative recipe (jsonld + parsed/roled `recipe_ingredients`,
   joined to `taxonomy_nodes.slug`) into a verb-frame `recipe`. Ingredient names
   are the **taxonomy slug** when the mapper resolved one (the Barbot
   slug→object seam), else a kebab-slug of the parsed name.
   - **Single sources of truth, no re-derivation.** Unit *validity* is
     RecipeGF's `UnitValidator` — the converter keeps no parallel unit table,
     only a small parser→RecipeGF alias bridge (`tbsp→Tbs`, `pint→pnt`,
     `quart→qt`, `gallon→gal`) for spellings RecipeGF doesn't alias; anything
     with no faithful RecipeGF unit → review. Ingredient **bucketing**
     (ice/garnish/body) trusts dedup's `role` tag rather than re-detecting it,
     so a missing role → review (also a de-facto freshness guard, since export
     runs after cluster compute). *(The parser's own `units.py` and dedup's
     `_OZ_PER_UNIT` are separate pre-RecipeGF unit tables — see "Unit coverage"
     below for how they consolidate.)*
4. **Validate + bundle** —
   [`bundle.py`](../ingredients/src/ingredients/recipegf/bundle.py) assembles the
   pin-2 shape and enforces the seam guarantees. Every `Ok` recipe is validated
   against `core ∪ spiritolo/` before it can leave.

Anything uncertain routes to **propose→review** (`recipegf_proposals`,
mirroring `taxonomy_proposals`) with a stable reason code, and the cluster is
parked at the current `CONVERTER_VERSION` so it drops off the queue until a
version bump or `--reset`. An LLM Phase 2 could later drain the review queue
behind the same seam.

### Uncertain reason codes

| Reason | Meaning |
|---|---|
| `no_slug` | canonical_name yields no valid kebab slug |
| `no_technique` | no stir/shake/build/blend keyword in instructions |
| `muddle_unsupported` | instructions mention muddling; v1 templates can't place a muddle step |
| `missing_roles` | an ingredient has no dedup role (cluster compute hasn't tagged this recipe) |
| `unresolved_ingredient` | a row has no taxonomy slug and no parseable name |
| `unknown_unit` | a unit has no faithful RecipeGF equivalent (e.g. `part`) |
| `missing_amount` | a body ingredient has a unit but no amount |
| `duplicate_ingredient` | two ingredients resolve to the same name |
| `no_body` | nothing left to mix after removing ice/garnish |
| `validation_failed` | assembled doc failed `RecipeValidator` (should be rare) |

## Unit coverage & the consolidation direction

RecipeGF currently recognizes only **~21 of Spiritolo's ~66 canonical units**
(the values `parser/units.py` emits). The other ~45 have no RecipeGF equivalent
today, so the converter **abstains** on them (`unknown_unit` → review) — nothing
is silently dropped, but those recipes don't export until the unit exists in
RecipeGF.

**The fix is to migrate Spiritolo's hard-won vocabulary INTO RecipeGF's
registries (an upstream RecipeGF PR — RecipeGF is the shared contract), then
retire `units.py`, dedup's `_OZ_PER_UNIT`, and this stage's alias bridge.** Not
the reverse: collapsing onto today's RecipeGF would lose those 45. Regenerate
the exact gap any time with a diff of `units.py`'s canonical values against
`recipegf.UnitValidator.is_valid`. The gap, categorized:

- **Pure spelling** RecipeGF should just alias: `tbsp→Tbs`, `pint→pnt`,
  `quart→qt`, `gallon→gal` (this stage's 4-entry bridge is the stopgap).
- **Bar measures with a known volume** → add to `bar-units.yaml` with
  `approx_ml`: `jigger`, `pony`, `shot`, `dropper`, `squeeze`.
- **Shaped-piece count nouns** (same shape as RecipeGF's `slice`/`wedge`/`wheel`)
  → add to `count-units.yaml`: `leaf`, `stick`, `clove`, `pod`, `bean`, `scoop`,
  `strip`, `stalk`, `sheet`, `ring`, `segment`, `spear`, `disc`, `coin`,
  `quarter`, `half`, `chunk`, `seed`, `zest`, `peel`.
- **Deliberately hard** (per-unit judgment; some may stay unrepresentable):
  `part` (a *ratio*, not an absolute amount), container counts `bottle`/`can`/
  `bag`/`bunch`/`packet`/`package` (volume is product-dependent — already flagged
  in `units.py`), and vague `grind`/`sprinkle`/`handful`/`knob`/`swath`.

`cube` is **not** in the gap: RecipeGF already aliases `cube → each`.

## `spiritolo/` extension verbs

Beyond RecipeGF core (`add`, `stir`, `shake`, `strain`, `muddle`, `rim`,
`garnish`, `express`), Spiritolo defines extension verbs as self-describing YAML
under
[`recipegf/verbs/`](../ingredients/src/ingredients/recipegf/verbs), loaded via
the overlay API (D2b: iterate verbs in-repo, no RecipeGF PR per verb):

- `spiritolo/blend` — blend in place until smooth (frozen drinks).
- `spiritolo/top` — top a built drink with an (effervescent) ingredient, added
  last without mixing.

A bundle embeds only the defs its recipe actually uses.

## Storage

Per-cluster bundle + provenance is written onto `recipe_clusters` (columns added
by [`20260711120000_recipegf_export.sql`](../supabase/migrations/20260711120000_recipegf_export.sql)):
`recipegf_slug`, `recipegf_bundle` (jsonb), `recipegf_source`, `recipegf_version`,
`recipegf_status` (`exported` | `uncertain`), `recipegf_exported_at`. The review
queue is the `recipegf_proposals` table.

## CLI

```bash
# Convert every cluster lacking a current-version bundle. Writes bundles onto
# recipe_clusters + parks uncertain drinks into recipegf_proposals.
cd ingredients && uv run python -m ingredients.cli recipegf-export

# Scoped + capped; also dump each bundle as <slug>.json into a directory.
cd ingredients && uv run python -m ingredients.cli recipegf-export \
    --site punch --limit 50 --out data/recipegf

# Preview without touching the DB (still writes --out files if given).
cd ingredients && uv run python -m ingredients.cli recipegf-export --dry-run --out /tmp/bundles

# Run the eval set (real-recipe fixtures; no DB needed).
cd ingredients && uv run python -m ingredients.cli recipegf-export --review

# Walk the propose→review queue.
cd ingredients && uv run python -m ingredients.cli recipegf-export review-proposals

# After bumping CONVERTER_VERSION, re-export everything left at the old version.
cd ingredients && uv run python -m ingredients.cli recipegf-export \
    --reset --except-version v1 --yes
```

Bulk runs follow the local-restore-then-upload flow (see
[docs/upload.md](upload.md)); writes go to whatever `SUPABASE_DB_URL` points at.

## Versioning

`CONVERTER_VERSION` in
[`recipegf/version.py`](../ingredients/src/ingredients/recipegf/version.py). Bump
when conversion output would change for the same input (technique keywords, step
templates, slug rules, unit handling, the spiritolo verb set, the id encoding
version), then re-run with `--reset --except-version <prior>`.

## Eval set

[`recipegf/eval_set.py`](../ingredients/src/ingredients/recipegf/eval_set.py) —
real cocktails (Old Fashioned, Negroni, Margarita, Daiquiri, Frozen Daiquiri,
Gin & Tonic, Whiskey Highball) as should-export cases, plus should-abstain cases
(Mojito → muddle, no-technique, untranslatable unit). The converter is pure, so
the eval runs with no DB. Add a should-export case when you teach a new
template/technique; add a should-abstain case when you find an over-conversion.
