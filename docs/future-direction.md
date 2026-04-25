# Spiritolo — Future Direction

## Vision

A worldwide compendium of cocktail recipes — every recipe ever published online, with AI-powered substitutions, a graph of related recipes, and a data source for RecipeGF.

## Long-Term Features

- **Search** — full-text over recipe name + ingredients.
- **Spirits taxonomy** — canonical hierarchy of spirit type → category → brand (e.g., whiskey → bourbon → Buffalo Trace), with free-text ingredient strings mapped to canonical IDs.
- **Deduplication** — fuzzy matching across sources (same cocktail, different recipes) via normalized name + sorted ingredient-set hash.
- **Recipe graph / "similar drinks"** — interpretable ingredient-overlap similarity as a baseline, then embeddings via Supabase pgvector over structured features (ingredients + technique tokens), not raw recipe text.
- **AI substitutions** — given a recipe and available ingredients, suggest substitutions.
- **Completeness tracking** — how many known cocktails are covered, what's missing.
- **Data source for RecipeGF** (`/Users/ruddick/code-projects/RecipeGF`) — spiritolo provides structured cocktail recipe data that RecipeGF consumes.

## Decisions

- **Ingredient extraction is the bottleneck unlock.** Most other features (search-by-ingredient, dedup, taxonomy mapping, similarity, substitutions) need structured `(amount, unit, ingredient_name, modifier)` rows. Implement as another versioned LLM stage matching existing scraper conventions (`PROMPT_VERSION` constant, `--review` eval set, `--reset --except-version` re-run flow).
- **Free-text ingredient names first, canonical taxonomy IDs later.** Lets ingredient extraction and taxonomy curation finish on independent timelines; a separate mapping step joins them.
- **Search starts cheap.** Postgres `tsvector` over `name` + `jsonld->>'recipeIngredient'` ships before structured ingredients exist; upgrade is a small re-point of the trigger once they land.
- **Dedup key:** normalized name + sorted ingredient-set hash.
- **Ingredient-overlap similarity before embeddings.** Interpretable baseline that also tells you whether embeddings actually add value before committing to pgvector.
- **Embeddings on structured features, not raw recipe text.** Raw text similarity is dominated by site phrasing; structured features (ingredients + technique tokens) reflect what makes drinks similar.

## Roadmap

```
┌──────────────────── Independent tracks ────────────────────┐
│                                                            │
│  [A] Ingredient extraction      [B] Spirits taxonomy       │
│      LLM stage, versioned           tables for type →      │
│      → recipe_ingredients           category → brand       │
│      (amount, unit, name,           hierarchy + curated    │
│       modifier)                     content                │
│                                                            │
│  [C] Search + basic UI                                     │
│      tsvector over name +                                  │
│      jsonld->>'recipeIngredient';                          │
│      basic search box in web/                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
              │                  │
              ▼                  ▼
   ┌──────────────────┐   ┌──────────────────────────────┐
   │ [E] Dedup        │   │ [D] Map free-text ingredients│
   │  name +          │   │     → canonical taxonomy IDs │
   │  ingredient-set  │   │     (LLM or fuzzy match,     │
   │  hash            │   │      versioned)              │
   └──────────────────┘   └──────────────────────────────┘
              │                  │
              ▼                  ▼
        ┌──────────────────────────────────┐
        │ [F] Re-point search to structured│
        │     ingredients                  │
        │ [G] Ingredient-overlap           │
        │     similarity                   │
        └──────────────────────────────────┘
                       │
                       ▼
           ┌────────────────────────────┐
           │ [H] Embeddings → pgvector  │
           │     (structured features)  │
           └────────────────────────────┘
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
   [I] "Similar drinks" UI   [J] AI substitutions
```

Dependency notes:
- `[A]`, `[B]`, `[C]` are mutually independent — different tables, different skills, no shared code.
- `[D]` needs both `[A]` (free-text ingredient strings to resolve) and `[B]` (target taxonomy).
- `[E]` needs `[A]` for the ingredient-set component. A name-only pass works without `[A]`, at the cost of a second dedup pass when ingredient sets become available.
- `[F]` is a small re-point of `[C]`'s tsvector trigger to read from `recipe_ingredients` instead of the JSON-LD blob.
- `[H]` benefits a lot from `[E]` — without dedup, "similar" tends to mean "duplicate from another site."
